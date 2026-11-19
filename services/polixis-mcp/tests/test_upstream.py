import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import UTC
from typing import override

import httpx2
from mcp_openapi.upstream import Operation
from pydantic import AnyHttpUrl
from pydantic import ValidationError
import pytest

from polixis_mcp.shared import CachedAnswer
from polixis_mcp.upstream import open_upstream
from polixis_mcp.upstream import SEARCH_ENTITIES
from polixis_mcp.upstream import SearchEntitiesRequest
from polixis_mcp.upstream import SearchRequestInput
from polixis_mcp.upstream import upstream_http
from polixis_mcp.upstream import UpstreamError
from polixis_mcp.upstream import UpstreamSettings
from polixis_mcp.upstream.answers import _OPERATIONS
from polixis_mcp.upstream.generated import operations
from tests.offline_server import fake_upstream_settings
from tests.offline_server import FakeResponseCache

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


async def test_a_cached_answer_fetches_no_token_once_the_token_expired() -> None:
    moments = [_WHEN]
    sent: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request.url.path)
        if request.url.path == _TOKEN_PATH:
            return _token("access-token", expires_in=60)
        return httpx2.Response(200, json={"status": "active"})

    async with upstream_http(
        fake_upstream_settings(),
        httpx2.MockTransport(respond),
        cache=FakeResponseCache(),
        now=lambda: moments[-1],
    ) as http:
        await http.get("/api/graph/pid/P1")
        moments.append(_WHEN + timedelta(minutes=5))
        await http.get("/api/graph/pid/P1")

    assert sent == [_TOKEN_PATH, "/api/graph/pid/P1"]


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


async def test_a_rate_limited_search_is_not_retried_with_retries_off() -> None:
    attempts = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        if request.url.path == _TOKEN_PATH:
            return _token("access-token")
        attempts += 1
        return httpx2.Response(429, headers={"Retry-After": "0"})

    settings = fake_upstream_settings().model_copy(update={"retry_enabled": False})
    transport = httpx2.MockTransport(respond)
    async with (
        upstream_http(settings, transport, now=lambda: _WHEN) as http,
        open_upstream(http, settings) as upstream,
    ):
        with pytest.raises(UpstreamError) as raised:
            await upstream.call(SEARCH_ENTITIES, _search())

    assert (raised.value.status_code, attempts) == (429, 1)


@pytest.mark.parametrize("field", ["api_url", "token_url"])
def test_settings_refuse_a_plain_http_endpoint(field: str) -> None:
    secrets = {"client_id": "id", "client_secret": "secret", "api_key": "key"}

    with pytest.raises(ValidationError, match="URL scheme should be 'https'"):
        UpstreamSettings.model_validate({**secrets, field: "http://api.example.com"})


def _polixis(answer: dict[str, object]) -> httpx2.MockTransport:
    """Answers the token request, and every other one with `answer`."""

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _TOKEN_PATH:
            return _token("access-token")
        return httpx2.Response(200, json=answer)

    return httpx2.MockTransport(respond)


async def test_an_answer_that_does_not_fit_its_model_is_not_cached() -> None:
    cache = FakeResponseCache()

    async with upstream_http(
        fake_upstream_settings(), _polixis({"count": "many"}), cache=cache
    ) as http:
        await http.get("/api/graph/pid/P1")

    assert cache.answers == {}


async def test_an_answer_to_a_route_no_operation_has_is_not_cached() -> None:
    cache = FakeResponseCache()

    async with upstream_http(fake_upstream_settings(), _polixis({}), cache=cache) as http:
        await http.get("/api/completion/fields")

    assert cache.answers == {}


async def test_a_cached_answer_that_no_longer_fits_is_fetched_again_and_replaced() -> None:
    cache = FakeResponseCache()
    settings = fake_upstream_settings()
    async with upstream_http(settings, _polixis({"count": 1}), cache=cache) as http:
        await http.get("/api/graph/pid/P1")
    [(key, answer)] = cache.answers.items()
    cache.answers[key] = answer.model_copy(update={"body": b'{"count": "many"}'})

    async with upstream_http(settings, _polixis({"count": 2}), cache=cache) as http:
        response = await http.get("/api/graph/pid/P1")

    assert response.json() == {"count": 2}
    assert cache.answers[key].body == b'{"count":2}'


async def test_an_answer_is_not_reused_for_another_polixis_origin() -> None:
    cache = FakeResponseCache()
    other = fake_upstream_settings().model_copy(
        update={"api_url": AnyHttpUrl("https://other.example.com")}
    )
    answered: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _TOKEN_PATH:
            return _token("access-token")
        answered.append(str(request.url.host))
        return httpx2.Response(200, json={"count": 1})

    async with upstream_http(
        fake_upstream_settings(), httpx2.MockTransport(respond), cache=cache
    ) as http:
        await http.get("/api/graph/pid/P1")
    cached = len(cache.answers)
    async with upstream_http(other, httpx2.MockTransport(respond), cache=cache) as http:
        await http.get("/api/graph/pid/P1")

    assert cached == 1
    assert answered == ["api.example.com", "other.example.com"]


def test_the_cache_knows_the_model_of_every_generated_operation() -> None:
    members: list[object] = list(vars(operations).values())
    generated = {member.operation_id for member in members if isinstance(member, Operation)}

    assert {operation.operation_id for operation in _OPERATIONS} == generated


async def test_a_rejection_is_not_cached_for_a_model_without_an_error_field() -> None:
    cache = FakeResponseCache()
    rejection: dict[str, object] = {"count": 1, "error": "unknown id", "code": "NOT_FOUND"}

    async with upstream_http(fake_upstream_settings(), _polixis(rejection), cache=cache) as http:
        await http.get("/api/graph/pid/P1")

    assert cache.answers == {}


@pytest.mark.parametrize("api_path", ["/regional%20api", "/v1%2F"])
async def test_an_answer_under_an_encoded_api_path_is_cached(api_path: str) -> None:
    cache = FakeResponseCache()
    settings = fake_upstream_settings().model_copy(
        update={"api_url": AnyHttpUrl(f"https://api.example.com{api_path}")}
    )

    async with upstream_http(settings, _polixis({"count": 1}), cache=cache) as http:
        await http.get("/api/graph/pid/P1")

    assert len(cache.answers) == 1


async def test_an_encoded_slash_and_a_slash_are_cached_apart() -> None:
    cache = FakeResponseCache()
    answered: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _TOKEN_PATH:
            return _token("access-token")
        answered.append(encoded(request))
        return httpx2.Response(200, json={"count": 1})

    def encoded(request: httpx2.Request) -> str:
        return request.url.raw_path.decode("ascii")

    for api_path in ("/region%2Fwest", "/region/west"):
        settings = fake_upstream_settings().model_copy(
            update={"api_url": AnyHttpUrl(f"https://api.example.com{api_path}")}
        )
        async with upstream_http(settings, httpx2.MockTransport(respond), cache=cache) as http:
            await http.get("/api/graph/pid/P1")

    assert len(cache.answers) == 2
    assert answered == [
        "/region%2Fwest/api/graph/pid/P1",
        "/region/west/api/graph/pid/P1",
    ]


async def test_a_path_that_only_starts_like_the_api_path_is_not_cached() -> None:
    cache = FakeResponseCache()
    settings = fake_upstream_settings().model_copy(
        update={"api_url": AnyHttpUrl("https://api.example.com/v1")}
    )

    async with upstream_http(settings, _polixis({"count": 1}), cache=cache) as http:
        await http.get("https://api.example.com/v1api/graph/pid/P1")

    assert cache.answers == {}


async def test_the_cache_key_holds_no_credentials_from_the_api_url() -> None:
    cache = FakeResponseCache()
    settings = fake_upstream_settings().model_copy(
        update={"api_url": AnyHttpUrl("https://user:secret@api.example.com")}
    )

    async with upstream_http(settings, _polixis({"count": 1}), cache=cache) as http:
        await http.get("/api/graph/pid/P1")

    [key] = cache.answers
    assert "secret" not in key
    assert "user" not in key


class _MissCountingCache(FakeResponseCache):
    """Sets `all_missed` once `expected` reads have missed."""

    def __init__(self, *, expected: int) -> None:
        super().__init__()
        self._expected: int = expected
        self.misses: int = 0
        self.all_missed: asyncio.Event = asyncio.Event()

    @override
    async def get(self, key: str) -> CachedAnswer | None:
        answer = await super().get(key)
        if answer is None:
            self.misses += 1
            if self.misses >= self._expected:
                self.all_missed.set()
        return answer


async def _three_at_once(answer: dict[str, object]) -> tuple[list[str], list[httpx2.Response]]:
    """Sends the same request three times at once, while Polixis holds the first answer back
    until all three have missed the cache. Returns the paths Polixis answered and the responses.
    """
    answered: list[str] = []
    cache = _MissCountingCache(expected=3)

    async def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _TOKEN_PATH:
            return _token("access-token")
        answered.append(request.url.path)
        await cache.all_missed.wait()
        return httpx2.Response(200, json=answer)

    async with (
        upstream_http(fake_upstream_settings(), httpx2.MockTransport(respond), cache=cache) as http,
        asyncio.timeout(5),
        asyncio.TaskGroup() as requests,
    ):
        sent = [requests.create_task(http.get("/api/graph/pid/P1")) for _ in range(3)]
    return answered, [request.result() for request in sent]


async def test_the_same_request_missing_at_once_asks_polixis_once() -> None:
    answered, responses = await _three_at_once({"count": 1})

    assert answered == ["/api/graph/pid/P1"]
    assert [response.json() for response in responses] == [{"count": 1}] * 3


async def test_after_an_answer_the_cache_does_not_keep_each_waiting_request_asks_again() -> None:
    rejection: dict[str, object] = {"count": 1, "error": "unknown id", "code": "NOT_FOUND"}

    answered, responses = await _three_at_once(rejection)

    assert answered == ["/api/graph/pid/P1"] * 3
    assert [response.json() for response in responses] == [rejection] * 3


async def test_a_miss_no_other_request_shares_reads_the_cache_once() -> None:
    cache = _MissCountingCache(expected=1)

    async with upstream_http(fake_upstream_settings(), _polixis({"count": 1}), cache=cache) as http:
        await http.get("/api/graph/pid/P1")

    assert cache.misses == 1


async def test_a_request_waits_at_most_the_timeout_for_the_same_one_ahead_of_it() -> None:
    answered: list[str] = []
    first_arrived = asyncio.Event()
    release_first = asyncio.Event()

    async def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _TOKEN_PATH:
            return _token("access-token")
        answered.append(request.url.path)
        count = len(answered)
        if count == 1:
            first_arrived.set()
            await release_first.wait()
        return httpx2.Response(200, json={"count": count})

    settings = fake_upstream_settings().model_copy(update={"timeout_seconds": 0.05})
    async with (
        upstream_http(settings, httpx2.MockTransport(respond), cache=FakeResponseCache()) as http,
        asyncio.timeout(5),
        asyncio.TaskGroup() as requests,
    ):
        first = requests.create_task(http.get("/api/graph/pid/P1"))
        await first_arrived.wait()
        second = await http.get("/api/graph/pid/P1")
        release_first.set()

    assert answered == ["/api/graph/pid/P1"] * 2
    assert (first.result().json(), second.json()) == ({"count": 1}, {"count": 2})


async def test_an_answer_that_repeats_a_key_with_a_value_that_does_not_fit_is_not_cached() -> None:
    cache = FakeResponseCache()
    body = b'{"nodes": {"N1": false, "N1": {"id": "N1"}}}'

    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == _TOKEN_PATH:
            return _token("access-token")
        return httpx2.Response(200, content=body, headers={"content-type": "application/json"})

    async with upstream_http(
        fake_upstream_settings(), httpx2.MockTransport(respond), cache=cache
    ) as http:
        await http.post("/api/graph/subgraph", json={"pids": ["P1"]})

    assert cache.answers == {}
