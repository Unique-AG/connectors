import asyncio
from typing import override

from fastmcp import Client
import httpx2
from key_value.aio.stores.memory import MemoryStore
import pytest

from polixis_mcp import contexts
from polixis_mcp.persistence import cull_expired_entries_periodically
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import UpstreamSettings
from tests.offline_server import build_server
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
        cull_expired_entries_periodically(Persistence(store=_ClosingPoolStore()))
    )
    await asyncio.sleep(0.01)

    try:
        assert not culling.done()
        assert caplog.messages == ["Could not delete the expired store entries"]
    finally:
        culling.cancel()


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
    persistence = Persistence(store=_FailingWriteStore())
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
    persistence = Persistence(store=_FailingReadStore())
    async with Client(build_server(upstream_settings, persistence, upstream_transport)) as client:
        owners = await call_tool(
            client,
            "get_ultimate_beneficial_owners",
            {"pid": "O00000000000000000000000000000100"},
            returns=contexts.OwnershipPage,
        )

    assert owners.entities
    assert "Could not read the Polixis response cache, asking Polixis" in caplog.messages
