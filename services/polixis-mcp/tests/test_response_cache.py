import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import UTC
from typing import override

from fastmcp import Client
from fastmcp import FastMCP
import httpx2
from pydantic import ValidationError
import pytest

from polixis_mcp import contexts
from polixis_mcp.mcp import create_server
from polixis_mcp.persistence import cull_expired_entries_periodically
from polixis_mcp.persistence import Persistence
from polixis_mcp.shared import CachedAnswer
from polixis_mcp.upstream import CacheSettings
from polixis_mcp.upstream import UpstreamSettings
from tests.offline_server import fake_cache_settings
from tests.offline_server import fake_persistence
from tests.offline_server import FakeResponseCache
from tests.offline_server import FakeSignInState
from tests.polixis_responses import UNKNOWN_PID
from tests.tool_calls import call_tool
from tests.tool_calls import McpClient
from tests.tool_calls import tool_error

_OWNER = "O00000000000000000000000000000100"


async def test_the_next_page_reads_the_tree_from_the_cache(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    first = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"pid": "O00000000000000000000000000000100", "page_size": 1},
        returns=contexts.OwnershipPage,
    )
    second = await call_tool(
        mcp_client,
        "get_ultimate_beneficial_owners",
        {"cursor": first.next_cursor},
        returns=contexts.OwnershipPage,
    )

    assert [request.url.path for request in upstream_requests if "/api/" in request.url.path] == [
        "/api/graph/ubo/O00000000000000000000000000000100"
    ]
    assert [entity.pid for entity in second.results] == ["P00000000000000000000000000000700"]


async def test_another_tool_on_the_same_entity_reuses_the_graph(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    await call_tool(
        mcp_client,
        "find_flagged_parties",
        {"pid": "O00000000000000000000000000000100", "radius": 2},
        returns=contexts.FlaggedPartiesPage,
    )
    linked = await call_tool(
        mcp_client,
        "find_linked_companies",
        {"pid": "O00000000000000000000000000000100", "scope": "all"},
        returns=contexts.LinkedCompaniesPage,
    )

    assert sorted(
        request.url.path for request in upstream_requests if "/api/" in request.url.path
    ) == ["/api/graph/smart", "/api/graph/subgraph"]
    assert linked.total_companies == 3


async def test_another_request_is_not_answered_from_the_cache(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    for pid in ("O00000000000000000000000000000100", "O00000000000000000000000000000101"):
        await call_tool(
            mcp_client, "get_top_down_ownership", {"pid": pid}, returns=contexts.OwnershipPage
        )

    assert [request.url.path for request in upstream_requests if "/api/" in request.url.path] == [
        "/api/graph/topdown/O00000000000000000000000000000100",
        "/api/graph/topdown/O00000000000000000000000000000101",
    ]


async def test_the_server_culls_expired_entries_when_it_starts(
    mcp_client: McpClient, persistence: Persistence
) -> None:
    await call_tool(
        mcp_client,
        "get_top_down_ownership",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.OwnershipPage,
    )

    assert isinstance(persistence.sign_in_state, FakeSignInState)
    assert isinstance(persistence.response_cache, FakeResponseCache)
    assert persistence.sign_in_state.culls == 1
    assert persistence.response_cache.culls == [500 * 1_000_000]


async def test_a_tool_served_from_the_spec_is_answered_from_the_cache_too(
    upstream_settings: UpstreamSettings,
) -> None:
    sent: list[str] = []

    def polixis(request: httpx2.Request) -> httpx2.Response:
        sent.append(request.url.path)
        if request.url.host == "auth.example.com":
            return httpx2.Response(200, json={"access_token": "fake-token", "expires_in": 300})
        return httpx2.Response(200, json={"status": "active"})

    server = _server(upstream_settings, FakeResponseCache(), httpx2.MockTransport(polixis))
    async with Client(server) as client:
        for _ in range(2):
            await client.call_tool("resolve_permanent_id", {"pid": _OWNER})

    assert sent == ["/token", f"/api/graph/pid/{_OWNER}"]


async def test_a_rejected_response_is_not_cached(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    for _ in range(2):
        await tool_error(mcp_client, "get_top_down_ownership", {"pid": UNKNOWN_PID})

    assert [request.url.path for request in upstream_requests if "/api/" in request.url.path] == [
        f"/api/graph/topdown/{UNKNOWN_PID}",
        f"/api/graph/topdown/{UNKNOWN_PID}",
    ]


class _ClosingPoolSignInState(FakeSignInState):
    """Fails every cull with an error that is not a Postgres one, as a closing pool does."""

    @override
    async def cull(self) -> None:
        raise RuntimeError("The pool is closing")


async def test_a_failed_cull_is_logged_and_the_culling_goes_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = FakeResponseCache()
    culling = asyncio.create_task(
        cull_expired_entries_periodically(
            fake_persistence(cache, _ClosingPoolSignInState()), every=600, max_cache_bytes=1_000
        )
    )
    await asyncio.sleep(0.01)

    try:
        assert not culling.done()
        assert caplog.messages == ["Could not delete the expired sign-in state"]
        assert cache.culls == [1_000]
    finally:
        culling.cancel()


def _polixis_paths(requests: list[httpx2.Request]) -> list[str]:
    return [request.url.path for request in requests if request.url.host == "api.example.com"]


async def test_the_same_search_asked_again_is_answered_from_the_cache(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    for _ in range(2):
        await call_tool(
            mcp_client,
            "search_entities",
            {"name": "Example Holdings"},
            returns=contexts.EntitySearchResults,
        )

    assert _polixis_paths(upstream_requests) == ["/search/api"]


async def test_the_same_profile_asked_again_is_answered_from_the_cache(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    for _ in range(2):
        await call_tool(
            mcp_client,
            "get_entity_profiles",
            {"pids": ["O00000000000000000000000000000100"]},
            returns=contexts.EntityProfiles,
        )

    assert _polixis_paths(upstream_requests) == [
        "/api/completion/O00000000000000000000000000000100"
    ]


_TTL_SECONDS = 60


async def test_an_answer_is_stored_for_the_configured_ttl(
    upstream_settings: UpstreamSettings, upstream_transport: httpx2.MockTransport
) -> None:
    cache = FakeResponseCache()

    async with Client(
        _server(upstream_settings, cache, upstream_transport, ttl_seconds=_TTL_SECONDS)
    ) as client:
        await _owners(client)

    assert list(cache.ttls.values()) == [_TTL_SECONDS]


def _server(
    upstream_settings: UpstreamSettings,
    response_cache: FakeResponseCache,
    upstream_transport: httpx2.AsyncBaseTransport,
    **cache: object,
) -> FastMCP:
    settings = upstream_settings.model_copy(update={"cache": fake_cache_settings(**cache)})
    return create_server(settings, fake_persistence(response_cache), upstream_transport)


async def _top_down_twice(server: FastMCP) -> None:
    async with Client(server) as client:
        for _ in range(2):
            await call_tool(
                client,
                "get_top_down_ownership",
                {"pid": "O00000000000000000000000000000100"},
                returns=contexts.OwnershipPage,
            )


async def test_nothing_is_cached_with_the_cache_off(
    upstream_settings: UpstreamSettings,
    upstream_transport: httpx2.MockTransport,
    upstream_requests: list[httpx2.Request],
) -> None:
    cache = FakeResponseCache()

    await _top_down_twice(_server(upstream_settings, cache, upstream_transport, enabled=False))

    assert len(_polixis_paths(upstream_requests)) == 2
    assert cache.answers == {}


async def test_a_new_key_prefix_leaves_the_answers_cached_before_unread(
    upstream_settings: UpstreamSettings,
    upstream_transport: httpx2.MockTransport,
    upstream_requests: list[httpx2.Request],
) -> None:
    cache = FakeResponseCache()
    for prefix in ("v1", "v2"):
        await _top_down_twice(
            _server(upstream_settings, cache, upstream_transport, key_prefix=prefix)
        )

    assert len(_polixis_paths(upstream_requests)) == 2


def test_the_cache_keeps_an_answer_at_most_an_hour() -> None:
    with pytest.raises(ValidationError):
        CacheSettings.model_validate({"ttl_seconds": 60 * 60 + 1, "ttl_uncapped": False})


def test_an_uncapped_cache_keeps_an_answer_longer_than_an_hour() -> None:
    ten_years = 10 * 365 * 24 * 60 * 60

    settings = CacheSettings.model_validate({"ttl_seconds": ten_years, "ttl_uncapped": True})

    assert settings.ttl_seconds == ten_years


async def test_the_cull_runs_again_after_the_interval_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []

    async def stop_after_the_first_wait(seconds: float) -> None:
        waits.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "polixis_mcp.persistence.persistence.asyncio.sleep", stop_after_the_first_wait
    )
    sign_in_state, cache = FakeSignInState(), FakeResponseCache()

    with pytest.raises(asyncio.CancelledError):
        await cull_expired_entries_periodically(
            fake_persistence(cache, sign_in_state), every=600, max_cache_bytes=1_000
        )

    assert (sign_in_state.culls, cache.culls, waits) == (1, [1_000], [600])


class _FailingWriteCache(FakeResponseCache):
    """Fails every write, as a Postgres that went away does."""

    @override
    async def put(self, key: str, answer: CachedAnswer, *, ttl_seconds: int) -> None:
        raise RuntimeError("The connection is closed")


async def test_a_failed_cache_write_still_returns_polixis_answer(
    upstream_settings: UpstreamSettings,
    upstream_transport: httpx2.MockTransport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with Client(
        _server(upstream_settings, _FailingWriteCache(), upstream_transport)
    ) as client:
        owners = await call_tool(
            client,
            "get_ultimate_beneficial_owners",
            {"pid": "O00000000000000000000000000000100"},
            returns=contexts.OwnershipPage,
        )

    assert owners.results
    assert "Could not cache a Polixis response" in caplog.messages


class _FailingReadCache(FakeResponseCache):
    """Fails every read, as a Postgres that went away does."""

    @override
    async def get(self, key: str) -> CachedAnswer | None:
        raise RuntimeError("The connection is closed")


async def test_a_failed_cache_read_asks_polixis(
    upstream_settings: UpstreamSettings,
    upstream_transport: httpx2.MockTransport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with Client(
        _server(upstream_settings, _FailingReadCache(), upstream_transport)
    ) as client:
        owners = await call_tool(
            client,
            "get_ultimate_beneficial_owners",
            {"pid": "O00000000000000000000000000000100"},
            returns=contexts.OwnershipPage,
        )

    assert owners.results
    assert "Could not read the Polixis response cache, asking Polixis" in caplog.messages


async def _owners(client: McpClient) -> contexts.OwnershipPage:
    return await call_tool(
        client, "get_ultimate_beneficial_owners", {"pid": _OWNER}, returns=contexts.OwnershipPage
    )


async def test_a_result_straight_from_polixis_has_no_cached_at(mcp_client: McpClient) -> None:
    before = datetime.now(UTC)

    fresh = await _owners(mcp_client)

    assert fresh.freshness.cached_at is None
    assert before <= fresh.freshness.fetched_at <= datetime.now(UTC)


async def test_a_result_from_the_cache_says_when_it_was_cached(mcp_client: McpClient) -> None:
    before = datetime.now(UTC)
    fresh = await _owners(mcp_client)

    cached = await _owners(mcp_client)

    assert cached.freshness.cached_at is not None
    assert before <= cached.freshness.cached_at <= fresh.freshness.fetched_at
    assert cached.freshness.fetched_at >= fresh.freshness.fetched_at


async def test_profiles_report_the_cached_one_among_fresh_ones(mcp_client: McpClient) -> None:
    cached_pid, fresh_pid = _OWNER, "O00000000000000000000000000000101"
    await call_tool(
        mcp_client, "get_entity_profiles", {"pids": [cached_pid]}, returns=contexts.EntityProfiles
    )

    both = await call_tool(
        mcp_client,
        "get_entity_profiles",
        {"pids": [cached_pid, fresh_pid]},
        returns=contexts.EntityProfiles,
    )

    assert both.freshness.cached_at is not None


async def test_with_the_cache_off_no_result_has_a_cached_at(
    upstream_settings: UpstreamSettings, upstream_transport: httpx2.MockTransport
) -> None:
    server = _server(upstream_settings, FakeResponseCache(), upstream_transport, enabled=False)
    async with Client(server) as client:
        results = [await _owners(client) for _ in range(2)]

    assert [result.freshness.cached_at for result in results] == [None, None]


async def test_an_entry_cached_longer_ago_than_a_shortened_ttl_is_fetched_again(
    upstream_settings: UpstreamSettings,
    upstream_transport: httpx2.MockTransport,
    upstream_requests: list[httpx2.Request],
) -> None:
    cache = FakeResponseCache()
    async with Client(_server(upstream_settings, cache, upstream_transport)) as client:
        await _owners(client)
    [(key, answer)] = cache.answers.items()
    ten_minutes_ago = datetime.now(UTC) - timedelta(minutes=10)
    cache.answers[key] = answer.model_copy(update={"cached_at": ten_minutes_ago})

    shortened = _server(upstream_settings, cache, upstream_transport, ttl_seconds=5 * 60)
    async with Client(shortened) as client:
        refetched = await _owners(client)

    assert refetched.freshness.cached_at is None
    assert len(_polixis_paths(upstream_requests)) == 2


async def test_a_cached_answer_is_served_while_the_quota_is_spent(
    upstream_settings: UpstreamSettings, upstream_transport: httpx2.MockTransport
) -> None:
    answered: list[str] = []

    async def polixis_until_one_answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.example.com":
            if answered:
                return httpx2.Response(
                    429, headers={"x-amzn-errortype": "LimitExceededException"}, json={}
                )
            answered.append(request.url.path)
        return await upstream_transport.handle_async_request(request)

    server = _server(
        upstream_settings, FakeResponseCache(), httpx2.MockTransport(polixis_until_one_answer)
    )
    async with Client(server) as client:
        fresh = await _owners(client)
        await tool_error(
            client, "get_ultimate_beneficial_owners", {"pid": "O00000000000000000000000000000101"}
        )
        cached = await _owners(client)

    assert cached.results == fresh.results
    assert cached.freshness.cached_at is not None
