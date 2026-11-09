from datetime import datetime
from datetime import timedelta
from datetime import UTC

import httpx2

from polixis_mcp.upstream import open_upstream
from polixis_mcp.upstream import SEARCH_ENTITIES
from polixis_mcp.upstream import SearchEntitiesRequest
from polixis_mcp.upstream import SearchRequestInput
from polixis_mcp.upstream import upstream_http
from tests.offline_server import fake_upstream_settings

_WHEN = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
_TOKEN_PATH = "/token"


def _token(access_token: str, *, expires_in: int = 300) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={"access_token": access_token, "token_type": "Bearer", "expires_in": expires_in},
    )


def _search() -> SearchEntitiesRequest:
    return SearchEntitiesRequest(body=SearchRequestInput(name="Example Holdings AG"))


async def test_a_call_sends_the_client_credentials_token_and_the_api_key() -> None:
    seen: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == _TOKEN_PATH:
            return _token("access-token")
        return httpx2.Response(204)

    transport = httpx2.MockTransport(respond)
    async with upstream_http(fake_upstream_settings(), transport, now=lambda: _WHEN) as http:
        await http.get("/api/graph/pid/P1")

    token, api = seen
    assert str(token.url) == "https://auth.example.com/token"
    assert dict(httpx2.QueryParams(token.content.decode())) == {
        "grant_type": "client_credentials",
        "client_id": "dummy-client-id",
        "client_secret": "dummy-client-secret",
    }
    assert "x-api-key" not in token.headers
    assert api.headers["Authorization"] == "Bearer access-token"
    assert api.headers["x-api-key"] == "dummy-api-key"


async def test_a_second_call_reuses_the_token() -> None:
    tokens = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal tokens
        if request.url.path == _TOKEN_PATH:
            tokens += 1
            return _token("access-token")
        return httpx2.Response(204)

    transport = httpx2.MockTransport(respond)
    async with upstream_http(fake_upstream_settings(), transport, now=lambda: _WHEN) as http:
        await http.get("/api/graph/pid/P1")
        await http.get("/api/graph/pid/P1")

    assert tokens == 1


async def test_an_expired_token_is_fetched_again() -> None:
    moments = iter((_WHEN, _WHEN + timedelta(seconds=31)))
    tokens: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _TOKEN_PATH:
            tokens.append(f"access-{len(tokens) + 1}")
            return _token(tokens[-1], expires_in=60)
        return httpx2.Response(204)

    transport = httpx2.MockTransport(respond)
    async with upstream_http(
        fake_upstream_settings(), transport, now=lambda: next(moments)
    ) as http:
        await http.get("/api/graph/pid/P1")
        await http.get("/api/graph/pid/P1")

    assert tokens == ["access-1", "access-2"]


async def test_a_rejected_token_is_refreshed_once() -> None:
    tokens: list[str] = []
    bearers: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _TOKEN_PATH:
            tokens.append(f"access-{len(tokens) + 1}")
            return _token(tokens[-1])
        bearers.append(request.headers["Authorization"])
        if len(bearers) == 1:
            return httpx2.Response(401)
        return httpx2.Response(200, json={"hits": [], "pagination": {"totalHits": 0}})

    settings = fake_upstream_settings()
    transport = httpx2.MockTransport(respond)
    async with (
        upstream_http(settings, transport, now=lambda: _WHEN) as http,
        open_upstream(http, settings) as upstream,
    ):
        response = await upstream.call(SEARCH_ENTITIES, _search())

    assert response.hits == []
    assert bearers == ["Bearer access-1", "Bearer access-2"]


async def test_a_rate_limited_search_is_retried() -> None:
    attempts = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        if request.url.path == _TOKEN_PATH:
            return _token("access-token")
        attempts += 1
        if attempts == 1:
            return httpx2.Response(429, headers={"Retry-After": "0"})
        return httpx2.Response(200, json={"hits": [], "pagination": {"totalHits": 0}})

    settings = fake_upstream_settings()
    transport = httpx2.MockTransport(respond)
    async with (
        upstream_http(settings, transport, now=lambda: _WHEN) as http,
        open_upstream(http, settings) as upstream,
    ):
        response = await upstream.call(SEARCH_ENTITIES, _search())

    assert response.pagination is not None
    assert response.pagination.total_hits == 0
    assert attempts == 2
