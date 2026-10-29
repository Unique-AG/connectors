from base64 import b64encode
from datetime import datetime
from datetime import timedelta
from datetime import UTC
from typing import cast

from fastmcp import Client
import httpx2
from key_value.aio.stores.memory import MemoryStore
from mcp_configs import RetrySettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr

from tests.offline_server import build_server
from world_check_mcp.persistence import Persistence
from world_check_mcp.upstream import GET_API_INFO
from world_check_mcp.upstream import open_upstream
from world_check_mcp.upstream import upstream_http
from world_check_mcp.upstream import UpstreamSettings

_CLIENT_ID = "service-account"
_CLIENT_SECRET = "top-secret"
_WHEN = datetime(2026, 10, 22, 6, 47, tzinfo=UTC)
_BASIC = "Basic " + b64encode(f"{_CLIENT_ID}:{_CLIENT_SECRET}".encode()).decode("ascii")


def _settings() -> UpstreamSettings:
    return UpstreamSettings(
        api_key=SecretStr(_CLIENT_ID),
        api_secret=SecretStr(_CLIENT_SECRET),
        api_url=AnyHttpUrl("https://api.risk.lseg.com/screening/v3"),
        token_url=AnyHttpUrl("https://api.risk.lseg.com/auth/oauth2/v1/token"),
        timeout_seconds=30,
        retry=RetrySettings(max_attempts=3, max_wait_seconds=0, statuses=frozenset({429, 503})),
    )


def _token(access_token: str, *, expires_in: int = 3600) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={"access_token": access_token, "token_type": "Bearer", "expires_in": expires_in},
    )


async def test_a_call_fetches_a_service_account_token_and_sends_it_as_a_bearer() -> None:
    seen: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == "/auth/oauth2/v1/token":
            return _token("access-token")
        return httpx2.Response(204)

    async with upstream_http(_settings(), httpx2.MockTransport(respond), now=lambda: _WHEN) as http:
        response = await http.get("/apiInfo")

    assert response.status_code == 204
    token, api = seen
    assert token.method == "POST"
    assert str(token.url) == "https://api.risk.lseg.com/auth/oauth2/v1/token"
    assert token.headers["Authorization"] == _BASIC
    assert token.content == b"grant_type=client_credentials"
    assert api.headers["Authorization"] == "Bearer access-token"
    assert "Date" not in api.headers


async def test_a_second_call_reuses_the_token() -> None:
    tokens = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal tokens
        if request.url.path == "/auth/oauth2/v1/token":
            tokens += 1
            return _token("access-token")
        return httpx2.Response(204)

    async with upstream_http(_settings(), httpx2.MockTransport(respond), now=lambda: _WHEN) as http:
        await http.get("/apiInfo")
        await http.get("/apiInfo")

    assert tokens == 1


async def test_an_expired_token_is_fetched_again() -> None:
    moments = iter((_WHEN, _WHEN + timedelta(seconds=31)))
    tokens: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/auth/oauth2/v1/token":
            access_token = f"access-{len(tokens) + 1}"
            tokens.append(access_token)
            return _token(access_token, expires_in=60)
        return httpx2.Response(204)

    async with upstream_http(
        _settings(), httpx2.MockTransport(respond), now=lambda: next(moments)
    ) as http:
        await http.get("/apiInfo")
        await http.get("/apiInfo")

    assert tokens == ["access-1", "access-2"]


async def test_a_rejected_token_is_refreshed_once() -> None:
    tokens: list[str] = []
    bearers: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/auth/oauth2/v1/token":
            access_token = f"access-{len(tokens) + 1}"
            tokens.append(access_token)
            return _token(access_token)
        bearers.append(request.headers["Authorization"])
        if len(bearers) == 1:
            return httpx2.Response(401)
        return httpx2.Response(
            200, json={"version": "3.9.0", "systemDateTime": "2026-10-22T06:47:00Z"}
        )

    settings = _settings()
    async with (
        upstream_http(settings, httpx2.MockTransport(respond), now=lambda: _WHEN) as http,
        open_upstream(http, settings) as upstream,
    ):
        info = await upstream.call(GET_API_INFO)

    assert info.version == "3.9.0"
    assert tokens == ["access-1", "access-2"]
    assert bearers == ["Bearer access-1", "Bearer access-2"]


async def test_a_retry_reuses_the_token() -> None:
    tokens = 0
    bearers: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal tokens
        if request.url.path == "/auth/oauth2/v1/token":
            tokens += 1
            return _token("access-token")
        bearers.append(request.headers["Authorization"])
        if len(bearers) == 1:
            return httpx2.Response(429, headers={"Retry-After": "0"})
        return httpx2.Response(
            200, json={"version": "3.9.0", "systemDateTime": "2026-10-22T06:47:00Z"}
        )

    settings = _settings()
    async with (
        upstream_http(settings, httpx2.MockTransport(respond), now=lambda: _WHEN) as http,
        open_upstream(http, settings) as upstream,
    ):
        info = await upstream.call(GET_API_INFO)

    assert info.version == "3.9.0"
    assert tokens == 1
    assert bearers == ["Bearer access-token", "Bearer access-token"]


async def test_get_api_info_does_not_ask_for_credentials() -> None:
    seen: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == "/auth/oauth2/v1/token":
            return _token("access-token")
        return httpx2.Response(
            200, json={"version": "3.9.0", "systemDateTime": "2026-10-22T06:47:00Z"}
        )

    server = build_server(
        _settings(), Persistence(store=MemoryStore()), httpx2.MockTransport(respond)
    )
    async with Client(server) as client:
        tools = await client.list_tools()
        await client.call_tool("get_api_info", {})

    tool = next(item for item in tools if item.name == "get_api_info")
    schema = cast(dict[str, object], tool.input_schema)
    properties = schema.get("properties", {})
    assert isinstance(properties, dict)
    assert "Authorization" not in properties
    assert "Date" not in properties
    api = next(request for request in seen if request.url.path != "/auth/oauth2/v1/token")
    assert api.headers["Authorization"] == "Bearer access-token"
