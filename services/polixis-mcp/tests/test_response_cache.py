import asyncio
from typing import override

from fastmcp import Client
from fastmcp import FastMCP
import httpx2
from key_value.aio.stores.memory import MemoryStore
from pydantic import ValidationError
import pytest

from polixis_mcp import contexts
from polixis_mcp.persistence import cull_expired_entries_periodically
from polixis_mcp.persistence import Persistence
from polixis_mcp.persistence import ResponseCacheSettings
from polixis_mcp.upstream import UpstreamSettings
from tests.offline_server import build_server
from tests.offline_server import fake_response_cache
from tests.offline_server import FakeStore
from tests.polixis_responses import UNKNOWN_PID
from tests.tool_calls import call_tool
from tests.tool_calls import McpClient
from tests.tool_calls import tool_error


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
    assert [entity.pid for entity in second.entities] == ["P00000000000000000000000000000700"]


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

    assert isinstance(persistence.store, FakeStore)
    assert persistence.store.culls == 1


async def test_a_cached_response_that_no_longer_fits_is_fetched_again(
    mcp_client: McpClient, persistence: Persistence, upstream_requests: list[httpx2.Request]
) -> None:
    owners: dict[str, object] = {"pid": "O00000000000000000000000000000100"}
    await call_tool(
        mcp_client, "get_ultimate_beneficial_owners", owners, returns=contexts.OwnershipPage
    )
    store = persistence.store
    assert isinstance(store, FakeStore)
    [collection] = await store.collections()
    [key] = await store.keys(collection)
    await store.put(key, {"roots": "not a list"}, collection=collection)

    refetched = await call_tool(
        mcp_client, "get_ultimate_beneficial_owners", owners, returns=contexts.OwnershipPage
    )
    await call_tool(
        mcp_client, "get_ultimate_beneficial_owners", owners, returns=contexts.OwnershipPage
    )

    assert refetched.total_entities == 3
    assert [request.url.path for request in upstream_requests if "/api/" in request.url.path] == [
        "/api/graph/ubo/O00000000000000000000000000000100",
        "/api/graph/ubo/O00000000000000000000000000000100",
    ]


async def test_a_rejected_response_is_not_cached(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    for _ in range(2):
        await tool_error(mcp_client, "get_top_down_ownership", {"pid": UNKNOWN_PID})

    assert [request.url.path for request in upstream_requests if "/api/" in request.url.path] == [
        f"/api/graph/topdown/{UNKNOWN_PID}",
        f"/api/graph/topdown/{UNKNOWN_PID}",
    ]


class _ClosingPoolStore(MemoryStore):
    """Fails every cull with an error that is not a Postgres one, as a closing pool does."""

    async def cull(self) -> None:
        raise RuntimeError("The pool is closing")


async def test_a_failed_cull_is_logged_and_the_culling_goes_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    culling = asyncio.create_task(
        cull_expired_entries_periodically(
            Persistence(store=_ClosingPoolStore(), response_cache=fake_response_cache())
        )
    )
    await asyncio.sleep(0.01)

    try:
        assert not culling.done()
        assert caplog.messages == ["Could not delete the expired store entries"]
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


async def test_a_cached_answer_expires_after_the_configured_ttl(
    mcp_client: McpClient, persistence: Persistence
) -> None:
    await call_tool(
        mcp_client,
        "get_top_down_ownership",
        {"pid": "O00000000000000000000000000000100"},
        returns=contexts.OwnershipPage,
    )
    store = persistence.store
    assert isinstance(store, FakeStore)
    [collection] = await store.collections()
    [key] = await store.keys(collection)
    _, ttl = await store.ttl(key, collection=collection)

    assert key.startswith("v1:getTopDownOwnership:")
    assert ttl is not None
    assert 15 * 60 - 5 < ttl <= 15 * 60


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
    store = FakeStore()
    persistence = Persistence(store=store, response_cache=fake_response_cache(enabled=False))

    await _top_down_twice(build_server(upstream_settings, persistence, upstream_transport))

    assert len(_polixis_paths(upstream_requests)) == 2
    assert await store.collections() == []


async def test_a_new_key_prefix_leaves_the_answers_cached_before_unread(
    upstream_settings: UpstreamSettings,
    upstream_transport: httpx2.MockTransport,
    upstream_requests: list[httpx2.Request],
) -> None:
    store = FakeStore()
    for prefix in ("v1", "v2"):
        persistence = Persistence(
            store=store, response_cache=fake_response_cache(key_prefix=prefix)
        )
        await _top_down_twice(build_server(upstream_settings, persistence, upstream_transport))

    assert len(_polixis_paths(upstream_requests)) == 2


def test_the_cache_keeps_an_answer_at_most_an_hour() -> None:
    with pytest.raises(ValidationError):
        ResponseCacheSettings.model_validate({"ttl_seconds": 60 * 60 + 1})


async def test_the_cull_runs_again_once_per_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []

    async def stop_after_the_first_wait(seconds: float) -> None:
        waits.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "polixis_mcp.persistence.response_cache.asyncio.sleep", stop_after_the_first_wait
    )
    store = FakeStore()
    persistence = Persistence(store=store, response_cache=fake_response_cache(ttl_seconds=600))

    with pytest.raises(asyncio.CancelledError):
        await cull_expired_entries_periodically(persistence)

    assert (store.culls, waits) == (1, [600])


class _FailingWriteStore(FakeStore):
    """Fails every write, as a Postgres that went away does."""

    @override
    async def put(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("The connection is closed")


async def test_a_failed_cache_write_still_returns_polixis_answer(
    upstream_settings: UpstreamSettings,
    upstream_transport: httpx2.MockTransport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    persistence = Persistence(store=_FailingWriteStore(), response_cache=fake_response_cache())
    async with Client(build_server(upstream_settings, persistence, upstream_transport)) as client:
        owners = await call_tool(
            client,
            "get_ultimate_beneficial_owners",
            {"pid": "O00000000000000000000000000000100"},
            returns=contexts.OwnershipPage,
        )

    assert owners.entities
    assert "Could not cache a Polixis response" in caplog.messages


class _FailingReadStore(FakeStore):
    """Fails every read, as a Postgres that went away does."""

    @override
    async def get(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("The connection is closed")


async def test_a_failed_cache_read_asks_polixis(
    upstream_settings: UpstreamSettings,
    upstream_transport: httpx2.MockTransport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    persistence = Persistence(store=_FailingReadStore(), response_cache=fake_response_cache())
    async with Client(build_server(upstream_settings, persistence, upstream_transport)) as client:
        owners = await call_tool(
            client,
            "get_ultimate_beneficial_owners",
            {"pid": "O00000000000000000000000000000100"},
            returns=contexts.OwnershipPage,
        )

    assert owners.entities
    assert "Could not read the Polixis response cache, asking Polixis" in caplog.messages
