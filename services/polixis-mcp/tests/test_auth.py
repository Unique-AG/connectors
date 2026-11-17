from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import StaticTokenVerifier
from fastmcp.server.auth.oidc_proxy import OIDCProxy
import httpx2
from mcp_configs import ServerSettings
from mcp_configs import ZitadelSettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr
import pytest
from starlette.applications import Starlette

from polixis_mcp.mcp import create_auth
from polixis_mcp.mcp import http_app
from polixis_mcp.persistence import Persistence
from polixis_mcp.persistence import StoreSettings
from polixis_mcp.upstream import UpstreamSettings
from tests.offline_server import build_server

ISSUER = "https://zitadel.example.com"
OIDC_CONFIGURATION = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/oauth/v2/authorize",
    "token_endpoint": f"{ISSUER}/oauth/v2/token",
    "jwks_uri": f"{ISSUER}/oauth/v2/keys",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
}
STORE = StoreSettings(
    url=SecretStr("postgresql://user:secret@localhost:5432/polixis"),
    _env_file=None,  # pyright: ignore[reportCallIssue]
)


@pytest.fixture
def zitadel_discovery(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The discovery URLs the proxy fetched, answered without a network."""
    requested: list[str] = []

    def get(url: str, **_: object) -> httpx2.Response:
        requested.append(url)
        return httpx2.Response(200, json=OIDC_CONFIGURATION, request=httpx2.Request("GET", url))

    monkeypatch.setattr(httpx2, "get", get)
    return requested


@pytest.fixture
def signed_in_app(
    *,
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    upstream_transport: httpx2.MockTransport,
    server_settings: ServerSettings,
) -> Starlette:
    signed_in = StaticTokenVerifier(
        tokens={"valid-token": {"client_id": "client", "scopes": [], "sub": "analyst"}}
    )
    server = build_server(upstream_settings, persistence, upstream_transport, auth=signed_in)
    return http_app(server, server_settings)


def test_create_auth_signs_no_one_in_without_zitadel_settings(
    server_settings: ServerSettings,
) -> None:
    assert create_auth(zitadel=None, server=server_settings, store=None) is None


def test_create_auth_signs_in_through_the_zitadel_it_is_given(
    server_settings: ServerSettings, zitadel_discovery: list[str]
) -> None:
    zitadel = ZitadelSettings(
        base_url=AnyHttpUrl(ISSUER),
        client_id="polixis",
        jwt_signing_key=SecretStr("k" * 32),
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    auth = create_auth(zitadel=zitadel, server=server_settings, store=STORE)

    assert isinstance(auth, OIDCProxy)
    assert zitadel_discovery == [f"{ISSUER}/.well-known/openid-configuration"]
    assert auth.required_scopes == zitadel.required_scopes


@pytest.mark.usefixtures("zitadel_discovery")
def test_create_auth_lets_a_client_register_with_the_organisation_scope(
    server_settings: ServerSettings,
) -> None:
    zitadel = ZitadelSettings(
        base_url=AnyHttpUrl(ISSUER),
        client_id="polixis",
        jwt_signing_key=SecretStr("k" * 32),
        org_id="123456789",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    auth = create_auth(zitadel=zitadel, server=server_settings, store=STORE)

    assert isinstance(auth, OIDCProxy)
    registration = auth.client_registration_options
    assert registration is not None
    assert registration.valid_scopes is not None
    assert set(zitadel.required_scopes) <= set(registration.valid_scopes)
    assert "urn:zitadel:iam:org:id:123456789" in registration.valid_scopes


@pytest.mark.usefixtures("zitadel_discovery")
def test_create_auth_asks_zitadel_for_a_refresh_token_without_requiring_one(
    server_settings: ServerSettings,
) -> None:
    zitadel = ZitadelSettings(
        base_url=AnyHttpUrl(ISSUER),
        client_id="polixis",
        jwt_signing_key=SecretStr("k" * 32),
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    auth = create_auth(zitadel=zitadel, server=server_settings, store=STORE)

    assert isinstance(auth, OIDCProxy)
    registration = auth.client_registration_options
    assert registration is not None
    assert registration.valid_scopes is not None
    assert "offline_access" in auth._extra_authorize_params["scope"].split()
    assert "offline_access" in registration.valid_scopes
    assert "offline_access" not in auth.required_scopes


@pytest.mark.usefixtures("zitadel_discovery")
def test_create_auth_asks_for_consent_once_per_client(server_settings: ServerSettings) -> None:
    zitadel = ZitadelSettings(
        base_url=AnyHttpUrl(ISSUER),
        client_id="polixis",
        jwt_signing_key=SecretStr("k" * 32),
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    auth = create_auth(zitadel=zitadel, server=server_settings, store=STORE)

    assert isinstance(auth, OIDCProxy)
    assert auth._require_authorization_consent == "remember"


async def test_a_request_without_a_token_is_refused(
    signed_in_app: Starlette, server_settings: ServerSettings
) -> None:
    async with (
        signed_in_app.router.lifespan_context(signed_in_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=signed_in_app), base_url=server_settings.base_url
        ) as http,
    ):
        response = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert response.status_code == 401


async def test_a_signed_in_caller_reaches_polixis_with_the_mcp_credentials(
    signed_in_app: Starlette,
    server_settings: ServerSettings,
    upstream_requests: list[httpx2.Request],
) -> None:
    def over_asgi(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        *,
        follow_redirects: bool = False,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=signed_in_app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=follow_redirects,
        )

    transport = StreamableHttpTransport(
        f"{server_settings.base_url}/mcp", auth="valid-token", httpx_client_factory=over_asgi
    )
    async with signed_in_app.router.lifespan_context(signed_in_app), Client(transport) as client:
        result = await client.call_tool("search_entities", {"name": "Example Holdings"})

    assert not result.is_error
    search = upstream_requests[-1]
    assert search.headers["Authorization"] == "Bearer fake-token"
    assert "valid-token" not in str(search.headers)
