"""The sign-in, end to end over HTTP: a client registers, its user signs in with their upstream
credentials, and each call it makes with the token acts for that user."""

import base64
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import hashlib
import re
from typing import cast

from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.dependencies import Depends
from fastmcp.server.http import StarletteWithLifespan
import httpx2
from mcp_configs import ServerSettings
import pytest

from mcp_skeleton.mcp import http_app
from mcp_skeleton.mcp.dependencies import get_credentials
from mcp_skeleton.persistence import Persistence
from mcp_skeleton.shared import CredentialsProvider
from mcp_skeleton.upstream import UpstreamSettings
from tests.offline_server import build_server

REDIRECT_URI = "http://localhost:6274/callback"
VERIFIER = "v" * 64
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)
USERS = {"ada": "s3cret", "grace": "hopper"}


def vendor(request: httpx2.Request) -> httpx2.Response:
    """Accepts the users in USERS, and nobody else."""
    expected = {
        "Basic " + base64.b64encode(f"{name}:{password}".encode()).decode()
        for name, password in USERS.items()
    }
    status = 200 if request.headers.get("Authorization") in expected else 401
    return httpx2.Response(status, json={})


@pytest.fixture
def app_server(upstream_settings: UpstreamSettings, persistence: Persistence) -> FastMCP:
    server = build_server(upstream_settings, persistence, httpx2.MockTransport(vendor))

    @server.tool
    async def whoami(credentials: CredentialsProvider = Depends(get_credentials)) -> str:
        """The upstream username the call acts for."""
        return (await credentials()).username

    return server


@pytest.fixture
def app(app_server: FastMCP, server_settings: ServerSettings) -> StarletteWithLifespan:
    return http_app(app_server, server_settings)


@asynccontextmanager
async def serving(
    app: StarletteWithLifespan, server_settings: ServerSettings
) -> AsyncGenerator[httpx2.AsyncClient]:
    """A client of the running app. Entered in the test itself: the app's lifespan has to end in
    the task it started in."""
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url=server_settings.base_url
        ) as http,
    ):
        yield http


async def register(client: httpx2.AsyncClient) -> str:
    response = await client.post(
        "/register",
        json={
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, str], response.json())["client_id"]


async def sign_in_form(client: httpx2.AsyncClient, client_id: str) -> tuple[str, str]:
    """Starts an authorization and opens the sign-in page it leads to: its request id and the
    form's CSRF token."""
    authorize = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "state": "state-1",
        },
    )
    assert authorize.status_code == 302, authorize.text
    location = httpx2.URL(authorize.headers["location"])
    assert location.path == "/sign-in"
    request_id = location.params["request_id"]
    page = await client.get("/sign-in", params={"request_id": request_id})
    assert page.status_code == 200
    return request_id, csrf_token_of(page)


def csrf_token_of(page: httpx2.Response) -> str:
    """Each form the page shows carries a new token, set in its cookie too."""
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token is not None
    return token.group(1)


async def submit(
    client: httpx2.AsyncClient, request_id: str, csrf_token: str, *, username: str, password: str
) -> httpx2.Response:
    return await client.post(
        "/sign-in",
        data={
            "request_id": request_id,
            "csrf_token": csrf_token,
            "username": username,
            "password": password,
        },
    )


async def sign_in(client: httpx2.AsyncClient, username: str) -> dict[str, str]:
    """The tokens the client gets once `username` signs in."""
    client_id = await register(client)
    request_id, csrf_token = await sign_in_form(client, client_id)
    signed_in = await submit(
        client, request_id, csrf_token, username=username, password=USERS[username]
    )
    assert signed_in.status_code == 302, signed_in.text
    callback = httpx2.URL(signed_in.headers["location"]).params
    assert callback["state"] == "state-1"
    tokens = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": callback["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": VERIFIER,
        },
    )
    assert tokens.status_code == 200, tokens.text
    return {**cast(dict[str, str], tokens.json()), "client_id": client_id}


async def call_whoami(app: StarletteWithLifespan, base_url: str, access_token: str) -> str:
    def over_asgi(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        *,
        follow_redirects: bool = False,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=follow_redirects,
        )

    transport = StreamableHttpTransport(
        f"{base_url}/mcp", auth=access_token, httpx_client_factory=over_asgi
    )
    async with Client(transport) as mcp:
        result = await mcp.call_tool("whoami", {})
    return cast(str, result.data)


async def test_each_call_acts_for_the_user_who_signed_in(
    app: StarletteWithLifespan, server_settings: ServerSettings
) -> None:
    async with serving(app, server_settings) as client:
        ada = await sign_in(client, "ada")
        grace = await sign_in(client, "grace")

        base_url = server_settings.base_url
        assert await call_whoami(app, base_url, ada["access_token"]) == "ada"
        assert await call_whoami(app, base_url, grace["access_token"]) == "grace"


async def test_wrong_credentials_are_refused_and_counted(
    app: StarletteWithLifespan, server_settings: ServerSettings
) -> None:
    async with serving(app, server_settings) as client:
        request_id, csrf_token = await sign_in_form(client, await register(client))

        refused: list[httpx2.Response] = []
        for _ in range(3):
            refused.append(
                await submit(client, request_id, csrf_token, username="ada", password="wrong")
            )
            csrf_token = csrf_token_of(refused[-1])
        throttled = await submit(client, request_id, csrf_token, username="ada", password="s3cret")

        assert [response.status_code for response in refused] == [401, 401, 401]
        assert "Wrong username or password." in refused[0].text
        assert throttled.status_code == 429


@pytest.mark.parametrize(
    "answer",
    [
        httpx2.Response(302, headers={"Location": "/login"}),
        httpx2.Response(500),
    ],
    ids=["a redirect to a login page", "a server error"],
)
async def test_an_upstream_answer_that_is_neither_yes_nor_no_signs_nobody_in(
    *,
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    server_settings: ServerSettings,
    answer: httpx2.Response,
) -> None:
    server = build_server(
        upstream_settings, persistence, httpx2.MockTransport(lambda _request: answer)
    )
    app = http_app(server, server_settings)
    async with serving(app, server_settings) as client:
        request_id, csrf_token = await sign_in_form(client, await register(client))

        response = await submit(client, request_id, csrf_token, username="ada", password="wrong")

    assert response.status_code == 503
    assert "The sign-in could not be checked." in response.text


async def test_a_form_without_its_csrf_cookie_is_refused(
    app: StarletteWithLifespan, server_settings: ServerSettings
) -> None:
    async with serving(app, server_settings) as client:
        request_id, csrf_token = await sign_in_form(client, await register(client))
        client.cookies.clear()

        response = await submit(client, request_id, csrf_token, username="ada", password="s3cret")

        assert response.status_code == 400
        assert "Your session expired" in response.text


async def test_an_unknown_sign_in_link_is_refused(
    app: StarletteWithLifespan, server_settings: ServerSettings
) -> None:
    async with serving(app, server_settings) as client:
        response = await client.get("/sign-in", params={"request_id": "unknown"})

        assert response.status_code == 400
        assert "has expired" in response.text


async def test_a_call_without_a_token_is_refused(
    app: StarletteWithLifespan, server_settings: ServerSettings
) -> None:
    async with serving(app, server_settings) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Accept": "application/json, text/event-stream"},
        )

        assert response.status_code == 401


async def test_a_refresh_token_works_once_and_its_reuse_signs_the_user_out(
    app: StarletteWithLifespan, server_settings: ServerSettings
) -> None:
    async with serving(app, server_settings) as client:
        tokens = await sign_in(client, "ada")

        def refresh(refresh_token: str) -> dict[str, str]:
            return {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": tokens["client_id"],
            }

        rotated = await client.post("/token", data=refresh(tokens["refresh_token"]))
        reused = await client.post("/token", data=refresh(tokens["refresh_token"]))
        rotated_refresh_token = cast(dict[str, str], rotated.json())["refresh_token"]
        after_reuse = await client.post("/token", data=refresh(rotated_refresh_token))

        assert rotated.status_code == 200
        assert (reused.status_code, reused.json()["error"]) == (401, "invalid_grant")
        assert (after_reuse.status_code, after_reuse.json()["error"]) == (401, "invalid_grant")
