from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from contextlib import asynccontextmanager
import json

from fastmcp.server.auth import AuthProvider
from fastmcp.server.auth import StaticTokenVerifier
from fastmcp.server.auth.oidc_proxy import OIDCProxy
import httpx2
from key_value.aio.stores.memory import MemoryStore
from mcp_configs import RateLimitSettings
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings
from mcp_types import CallToolResult
from mcp_types import TextContent
from pydantic import AnyHttpUrl
from pydantic import SecretStr
import pytest

from kyckr_mcp.mcp import create_auth
from kyckr_mcp.mcp import http_app
from kyckr_mcp.mcp.auth import IdTokenVerifier
from kyckr_mcp.persistence import Persistence
from kyckr_mcp.upstream import UpstreamSettings
from tests.conftest import FakeKyckr
from tests.offline_server import build_server

ORG_SCOPE = "urn:zitadel:iam:org:id:org-1"
ORG_CLAIM = "urn:zitadel:iam:user:resourceowner:id"
SEARCH = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "search_companies", "arguments": {"name": "Acme"}},
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
TOKENS: dict[str, dict[str, object]] = {
    "token-a": {"client_id": "client", "scopes": [], "sub": "user-a", ORG_CLAIM: "org-1"},
    "token-b": {"client_id": "client", "scopes": [], "sub": "user-b", ORG_CLAIM: "org-1"},
    "token-other-org": {"client_id": "client", "scopes": [], "sub": "user-c", ORG_CLAIM: "org-2"},
    "token-no-org": {"client_id": "client", "scopes": [], "sub": "user-d"},
}

type Serve = Callable[..., AbstractAsyncContextManager[httpx2.AsyncClient]]


def _zitadel(
    issuer: str, *, org_id: str | None = None, signing_key: str = "k" * 32
) -> ZitadelSettings:
    return ZitadelSettings(
        base_url=AnyHttpUrl(issuer),
        client_id="kyckr",
        jwt_signing_key=SecretStr(signing_key),
        org_id=org_id,
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


@pytest.fixture
def serve(
    *,
    upstream_settings: UpstreamSettings,
    upstream_transport: httpx2.MockTransport,
    server_settings: ServerSettings,
    persistence: Persistence,
) -> Serve:
    """A client of the server's HTTP app behind `auth`, with its lifespan running."""

    @asynccontextmanager
    async def served(
        auth: AuthProvider, rate_limit: RateLimitSettings | None = None
    ) -> AsyncGenerator[httpx2.AsyncClient]:
        server = build_server(
            upstream_settings, persistence, upstream_transport, auth=auth, rate_limit=rate_limit
        )
        app = http_app(server, server_settings)
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url=str(server_settings.base_url)
            ) as client,
        ):
            yield client

    return served


async def _search(client: httpx2.AsyncClient, token: str | None) -> httpx2.Response:
    authorization = {"Authorization": f"Bearer {token}"} if token else {}
    return await client.post("/mcp", json=SEARCH, headers={**MCP_HEADERS, **authorization})


def _tool_error(response: httpx2.Response) -> str | None:
    """The tool error text of a `tools/call` answer, or None when the tool succeeded."""
    data = next(line for line in response.text.splitlines() if line.startswith("data:"))
    result = CallToolResult.model_validate(json.loads(data.removeprefix("data:"))["result"])
    (content,) = result.content
    return content.text if result.is_error and isinstance(content, TextContent) else None


@pytest.mark.usefixtures("zitadel_discovery")
def test_create_auth_signs_in_with_identity_scopes_and_verifies_the_id_token(
    server_settings: ServerSettings,
) -> None:
    auth = create_auth(
        zitadel=_zitadel("https://zitadel.example.com"), server=server_settings, store=MemoryStore()
    )

    assert isinstance(auth, OIDCProxy)
    assert auth.required_scopes == ["openid", "profile", "urn:zitadel:iam:user:resourceowner"]
    # FastMCP has no public accessor for these; both are pinned by fastmcp's version in uv.lock.
    assert auth._verify_id_token
    assert isinstance(auth._token_validator, IdTokenVerifier)
    assert auth._token_validator._org_id is None


@pytest.mark.usefixtures("zitadel_discovery")
async def test_an_org_id_asks_zitadel_for_the_org_and_checks_it_on_every_token(
    server_settings: ServerSettings,
) -> None:
    zitadel = _zitadel("https://org.zitadel.example.com", org_id="org-1")

    auth = create_auth(zitadel=zitadel, server=server_settings, store=MemoryStore())

    assert ORG_SCOPE not in (auth.required_scopes or [])
    assert ORG_SCOPE in auth._extra_authorize_params["scope"].split()
    assert isinstance(auth._token_validator, IdTokenVerifier)
    assert auth._token_validator._org_id == "org-1"


@pytest.mark.usefixtures("zitadel_discovery")
async def test_a_client_registers_with_the_advertised_scopes_when_an_org_id_is_set(
    server_settings: ServerSettings, serve: Serve
) -> None:
    auth = create_auth(
        zitadel=_zitadel("https://register.zitadel.example.com", org_id="org-1"),
        server=server_settings,
        store=MemoryStore(),
    )
    registration_options = auth.client_registration_options
    assert registration_options is not None
    registration = {
        "redirect_uris": ["http://localhost:6274/callback"],
        "token_endpoint_auth_method": "none",
        "scope": " ".join(registration_options.valid_scopes or []),
    }

    async with serve(auth) as client:
        response = await client.post("/register", json=registration)

    assert response.status_code == 201, response.text


@pytest.mark.usefixtures("zitadel_discovery")
def test_offline_access_is_asked_for_and_registrable_but_not_required(
    server_settings: ServerSettings,
) -> None:
    auth = create_auth(
        zitadel=_zitadel("https://refresh.zitadel.example.com"),
        server=server_settings,
        store=MemoryStore(),
    )

    registration_options = auth.client_registration_options
    assert registration_options is not None
    assert "offline_access" in auth._extra_authorize_params["scope"].split()
    assert "offline_access" in (registration_options.valid_scopes or [])
    assert "offline_access" not in (auth.required_scopes or [])


@pytest.mark.usefixtures("zitadel_discovery")
def test_the_org_scope_is_not_a_scope_a_client_can_register(
    server_settings: ServerSettings,
) -> None:
    auth = create_auth(
        zitadel=_zitadel("https://org-scope.zitadel.example.com", org_id="org-1"),
        server=server_settings,
        store=MemoryStore(),
    )

    registration_options = auth.client_registration_options
    assert registration_options is not None
    assert ORG_SCOPE not in (registration_options.valid_scopes or [])


@pytest.mark.usefixtures("zitadel_discovery")
async def test_the_sign_in_state_is_encrypted_at_rest_with_the_signing_key(
    server_settings: ServerSettings,
) -> None:
    at_rest = MemoryStore()
    issuer = "https://store.zitadel.example.com"
    auth = create_auth(zitadel=_zitadel(issuer), server=server_settings, store=at_rest)
    rotated = create_auth(
        zitadel=_zitadel(issuer, signing_key="r" * 32), server=server_settings, store=at_rest
    )

    await auth._client_storage.put("client-1", {"token": "plain-token"}, collection="clients")

    stored = await at_rest.get("client-1", collection="clients")
    assert stored is not None
    assert "plain-token" not in str(stored)
    assert await auth._client_storage.get("client-1", collection="clients") == {
        "token": "plain-token"
    }
    assert await rotated._client_storage.get("client-1", collection="clients") is None


@pytest.mark.parametrize("token", [None, "unknown-token"])
async def test_a_call_without_a_known_token_is_refused(
    serve: Serve, kyckr: FakeKyckr, token: str | None
) -> None:
    async with serve(StaticTokenVerifier(tokens=TOKENS)) as client:
        response = await _search(client, token)

    assert response.status_code == 401
    assert kyckr.requests == []


async def test_a_call_with_a_valid_token_reaches_the_tool(serve: Serve, kyckr: FakeKyckr) -> None:
    kyckr.answers({"data": []})

    async with serve(StaticTokenVerifier(tokens=TOKENS)) as client:
        response = await _search(client, "token-a")

    assert response.status_code == 200
    assert [request.url.path for request in kyckr.requests] == ["/v2/companies"]


@pytest.mark.parametrize("token", ["token-other-org", "token-no-org"])
async def test_a_token_outside_the_org_is_refused(
    serve: Serve, kyckr: FakeKyckr, token: str
) -> None:
    async with serve(
        IdTokenVerifier(StaticTokenVerifier(tokens=TOKENS), org_id="org-1", required_scopes=[])
    ) as client:
        response = await _search(client, token)

    assert response.status_code == 401
    assert kyckr.requests == []


async def test_a_token_of_the_org_reaches_the_tool(serve: Serve, kyckr: FakeKyckr) -> None:
    kyckr.answers({"data": []})

    async with serve(
        IdTokenVerifier(StaticTokenVerifier(tokens=TOKENS), org_id="org-1", required_scopes=[])
    ) as client:
        response = await _search(client, "token-a")

    assert response.status_code == 200
    assert _tool_error(response) is None
    assert [request.url.path for request in kyckr.requests] == ["/v2/companies"]


async def test_the_rate_limit_counts_each_users_tool_calls_apart(
    serve: Serve, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"data": []})
    one_call = RateLimitSettings(tool_calls_per_window=1, window_seconds=60)

    async with serve(StaticTokenVerifier(tokens=TOKENS), one_call) as client:
        first = await _search(client, "token-a")
        second = await _search(client, "token-a")
        other_user = await _search(client, "token-b")

    assert _tool_error(first) is None
    assert _tool_error(second) == "Rate limit exceeded: 1 tool calls per 60 seconds"
    assert _tool_error(other_user) is None
    assert len(kyckr.requests) == 2
