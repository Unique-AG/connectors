"""The TTL / single-flight / serve-stale protocol every cached catalog inherits.

One suite over all four catalogs. It used to be four copies of the same twelve tests, differing
only in which route was mocked and which attribute was read back; the protocol itself now lives
in `features/cached_catalog.py`, so it is exercised once per catalog from here instead. What is
genuinely per-feature — which attributes survive the projection, which rows are dropped — stays
in that feature's own test file.

Each parameter case gets its own base URL prefix as well as its own per-test sub-path, so a
mocked route can leak neither across cases nor across tests.
"""

import asyncio
import gc
from collections.abc import AsyncGenerator, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Protocol, cast

import httpx
import pytest
import respx
from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.activity_tags import ActivityTagsService
from backstop_mcp.features.cached_catalog import CachedCatalog
from backstop_mcp.features.custom_fields import CustomFieldGroupsService, CustomFieldsService
from backstop_mcp.features.system_users import SystemUsersService
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]


class _NamedCatalogEntry(Protocol):
    """The one attribute every catalog DTO has, which is all this suite reads back."""

    @property
    def name(self) -> str | None: ...


# `CachedCatalog[T]` holds a mutable `dict[str, T]`, so it is invariant in `T` and the four
# concrete services have no common supertype. This is the shape the protocol tests need; each
# case casts to it, which is sound because nothing here reads more than `.name` off an entry.
type _Catalog = CachedCatalog[_NamedCatalogEntry]


class _CatalogUnderTest(BaseModel):
    """One catalog: how to build the service, and how to mock the walk it performs."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    slug: str
    path: str
    resource_type: str
    # Attributes a row needs beyond `name` for the feature's projection to keep it.
    required_attributes: Mapping[str, object] = {}
    build: Callable[[], _Catalog]

    def service(self) -> _Catalog:
        return self.build()

    def base_url(self, case: str) -> str:
        return f"{BASE_URL}/{self.slug}/{case}"

    def page(self, *rows: tuple[str, str]) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    resource(row_id, self.resource_type, name=name, **self.required_attributes)
                    for row_id, name in rows
                ],
                "links": {"next": None},
            },
        )

    def route(self, base_url: str, *rows: tuple[str, str]) -> respx.Route:
        return respx.get(f"{base_url}{self.path}").mock(return_value=self.page(*rows))


_CATALOGS: tuple[_CatalogUnderTest, ...] = (
    _CatalogUnderTest(
        slug="activity-tags",
        path="/activity-tags",
        resource_type="activity-tags",
        required_attributes={"quantityTagged": 3, "viewable": True},
        build=lambda: cast("_Catalog", ActivityTagsService.with_ttl_minutes(ttl_minutes=60)),
    ),
    _CatalogUnderTest(
        slug="custom-field-groups",
        path="/custom-field-groups",
        resource_type="custom-field-groups",
        build=lambda: cast("_Catalog", CustomFieldGroupsService.with_ttl_minutes(ttl_minutes=60)),
    ),
    _CatalogUnderTest(
        slug="system-users",
        path="/system-users",
        resource_type="system-users",
        build=lambda: cast("_Catalog", SystemUsersService.with_ttl_minutes(ttl_minutes=60)),
    ),
    _CatalogUnderTest(
        slug="custom-field-definitions",
        path="/custom-field-definitions",
        resource_type="custom-field-definitions",
        required_attributes={"entityType": "OrganizationBean", "fieldType": "text"},
        build=lambda: cast("_Catalog", CustomFieldsService.with_ttl_minutes(ttl_minutes=60)),
    ),
)


@pytest.fixture
async def clients() -> AsyncGenerator[ClientBuilder]:
    """Build a client per Backstop base URL.

    Each test uses its own sub-path as a distinct "instance" so mocked routes cannot leak
    across cases. The factory owns the base URL, so one is created per URL and all of them
    are closed together.
    """
    built: list[BackstopClientFactory] = []

    def make(base_url: str) -> BackstopClient:
        factory = client_factory(base_url)
        built.append(factory)
        return factory.for_credential(credential("schema-bob"))

    yield make
    for factory in built:
        await factory.aclose()


def _age_past_ttl(service: _Catalog) -> None:
    past = datetime.now(UTC) - timedelta(minutes=90)
    service._freshness.mark(past)  # pyright: ignore[reportPrivateUsage]


def _names(entries: Mapping[str, _NamedCatalogEntry]) -> list[str | None]:
    return [entry.name for entry in entries.values()]


async def _join_in_flight(started: asyncio.Event, release: asyncio.Event) -> None:
    """Unblock Backstop only after sibling refresh tasks have had a turn to join."""
    await started.wait()
    for _ in range(20):
        await asyncio.sleep(0)
    release.set()


@pytest.mark.parametrize("catalog", _CATALOGS, ids=[case.slug for case in _CATALOGS])
class TestInMemoryTtl:
    """The in-memory catalog is a cache with a TTL, not a permanent record."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_first_fetch_caches_by_id_and_second_get_does_not_rehit(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-fresh")
        service = catalog.service()
        route = catalog.route(base_url, ("7", "Cached Entry"))

        first, first_cache = await service.get(clients(base_url))
        second, second_cache = await service.get(clients(base_url))

        assert route.call_count == 1
        assert first_cache == "ok"
        assert second_cache == "ok"
        assert list(first) == ["7"]
        assert first["7"].name == "Cached Entry"
        assert second["7"].name == "Cached Entry"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_past_ttl_fetches_again(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-expired")
        service = catalog.service()
        route = respx.get(f"{base_url}{catalog.path}").mock(
            side_effect=[
                catalog.page(("old-1", "Stale Entry")),
                catalog.page(("new-1", "Fresh Entry")),
            ]
        )

        await service.get(clients(base_url))
        _age_past_ttl(service)
        entries, cache = await service.get(clients(base_url))

        assert route.call_count == 2
        assert cache == "ok"
        assert _names(entries) == ["Fresh Entry"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_fetches_even_when_fresh(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-refresh")
        service = catalog.service()
        route = respx.get(f"{base_url}{catalog.path}").mock(
            side_effect=[
                catalog.page(("old-1", "Cached Entry")),
                catalog.page(("new-1", "Refreshed Entry")),
            ]
        )

        await service.get(clients(base_url))
        entries, cache = await service.get(clients(base_url), refresh=True)

        assert route.call_count == 2
        assert cache == "ok"
        assert _names(entries) == ["Refreshed Entry"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_warm_read_does_not_queue_behind_an_in_flight_refresh(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        """A fresh `get()` must not block on the lock a refresh is holding."""
        base_url = catalog.base_url("ttl-warm-read-not-blocked")
        service = catalog.service()
        catalog.route(base_url, ("7", "Warm Entry"))
        await service.get(clients(base_url))

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(200, json={"data": [], "links": {"next": None}})

        respx.get(f"{base_url}{catalog.path}").mock(side_effect=blocked)

        refresh_task = asyncio.create_task(service.get(clients(base_url), refresh=True))
        await asyncio.wait_for(refresh_started.wait(), timeout=5)

        entries, cache = await asyncio.wait_for(service.get(clients(base_url)), timeout=1)
        assert cache == "ok"
        assert entries["7"].name == "Warm Entry"

        release_refresh.set()
        _ = await asyncio.wait_for(refresh_task, timeout=5)

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_cold_gets_produce_one_walk(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-single-flight")
        service = catalog.service()
        route = catalog.route(base_url, ("7", "Fresh Entry"))
        client = clients(base_url)

        results = await asyncio.gather(
            service.get(client),
            service.get(client),
            service.get(client),
        )

        assert route.call_count == 1
        for entries, cache in results:
            assert cache == "ok"
            assert entries["7"].name == "Fresh Entry"

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_refreshes_produce_one_walk(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-refresh-single-flight")
        service = catalog.service()
        client = clients(base_url)
        catalog.route(base_url, ("7", "Cached Entry"))
        await service.get(client)

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return catalog.page(("2", "Refreshed Entry"))

        route = respx.get(f"{base_url}{catalog.path}").mock(side_effect=blocked)

        warm_calls = route.call_count
        results = await asyncio.gather(
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            _join_in_flight(refresh_started, release_refresh),
        )

        assert route.call_count == warm_calls + 1
        for entries, cache in results[:3]:
            assert cache == "ok"
            assert _names(entries) == ["Refreshed Entry"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_failed_refreshes_share_stale(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-refresh-fail-single-flight")
        service = catalog.service()
        client = clients(base_url)
        catalog.route(base_url, ("7", "Cached Entry"))
        await service.get(client)

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_failure(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            raise httpx.ConnectError("backstop down")

        route = respx.get(f"{base_url}{catalog.path}").mock(side_effect=blocked_failure)

        warm_calls = route.call_count
        results = await asyncio.gather(
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            _join_in_flight(refresh_started, release_refresh),
        )

        assert route.call_count == warm_calls + 1
        for entries, cache in results[:3]:
            assert cache == "stale"
            assert entries["7"].name == "Cached Entry"

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_fetch_with_a_cache_keeps_stale(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-refresh-fails")
        service = catalog.service()
        catalog.route(base_url, ("old-1", "Stale Entry"))
        await service.get(clients(base_url))
        _age_past_ttl(service)

        respx.get(f"{base_url}{catalog.path}").mock(side_effect=httpx.ConnectError("backstop down"))

        entries, cache = await service.get(clients(base_url))

        assert cache == "stale"
        assert entries["old-1"].name == "Stale Entry"

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_refresh_restamps_ttl_so_the_next_get_does_not_refetch(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-stale-cooldown")
        service = catalog.service()
        catalog.route(base_url, ("old-1", "Stale Entry"))
        await service.get(clients(base_url))
        _age_past_ttl(service)

        failed = respx.get(f"{base_url}{catalog.path}").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        first, first_cache = await service.get(clients(base_url))
        calls_after_failure = failed.call_count
        second, second_cache = await service.get(clients(base_url))

        assert calls_after_failure >= 1
        assert failed.call_count == calls_after_failure
        assert first_cache == "stale"
        assert second_cache == "ok"
        assert first["old-1"].name == "Stale Entry"
        assert second["old-1"].name == "Stale Entry"

    @pytest.mark.asyncio
    @respx.mock
    async def test_cancelled_fetch_unblocks_waiters(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-cancel-waiters")
        service = catalog.service()
        client = clients(base_url)
        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(200, json={"data": [], "links": {"next": None}})

        respx.get(f"{base_url}{catalog.path}").mock(side_effect=blocked)

        owner = asyncio.create_task(service.get(client))
        await asyncio.wait_for(refresh_started.wait(), timeout=5)
        waiter = asyncio.create_task(service.get(client))
        for _ in range(20):
            await asyncio.sleep(0)

        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, timeout=5)
        with pytest.raises(RuntimeError, match="cancelled"):
            await asyncio.wait_for(waiter, timeout=1)

        release_refresh.set()

        catalog.route(base_url, ("7", "After Cancel"))
        entries, cache = await asyncio.wait_for(service.get(client), timeout=5)
        assert cache == "ok"
        assert entries["7"].name == "After Cancel"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_done_in_flight_future_does_not_block_the_next_get(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        """If unpinning is skipped, a finished future must not pin the catalog forever."""
        base_url = catalog.base_url("ttl-stale-in-flight")
        service = catalog.service()
        done = asyncio.get_running_loop().create_future()
        done.set_exception(RuntimeError("catalog fetch was cancelled"))
        _ = done.exception()
        service._in_flight = done  # pyright: ignore[reportPrivateUsage]
        route = catalog.route(base_url, ("7", "Recovered Entry"))

        entries, cache = await service.get(clients(base_url))

        assert cache == "ok"
        assert entries["7"].name == "Recovered Entry"
        assert route.call_count == 1
        assert service._in_flight is None  # pyright: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_fetch_with_no_cache_raises(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("ttl-cold-failure")
        service = catalog.service()
        respx.get(f"{base_url}{catalog.path}").mock(side_effect=httpx.ConnectError("backstop down"))

        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_cold_fetch_failure_does_not_leave_an_unretrieved_future(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        """The owner re-raises the fetch error instead of awaiting the shared future.

        `set_exception` is for waiters. With none, asyncio logs "Future exception was never
        retrieved" unless the owner also retrieves it.
        """
        base_url = catalog.base_url("ttl-cold-failure-retrieved")
        service = catalog.service()
        respx.get(f"{base_url}{catalog.path}").mock(side_effect=httpx.ConnectError("backstop down"))

        loop = asyncio.get_running_loop()
        leaked: list[object] = []
        previous = loop.get_exception_handler()

        def handler(handler_loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
            if context.get("message") == "Future exception was never retrieved":
                leaked.append(context.get("exception"))
                return
            if previous is not None:
                previous(handler_loop, context)

        loop.set_exception_handler(handler)
        try:
            with pytest.raises(httpx.ConnectError):
                await service.get(clients(base_url))
            gc.collect()
            await asyncio.sleep(0)
            assert leaked == []
        finally:
            loop.set_exception_handler(previous)

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_returned_catalog_is_a_copy(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        """A caller mutating what it was handed must not corrupt the shared catalog."""
        base_url = catalog.base_url("ttl-copy")
        service = catalog.service()
        catalog.route(base_url, ("7", "Shared Entry"))

        first, _cache = await service.get(clients(base_url))
        first.clear()
        second, _second_cache = await service.get(clients(base_url))

        assert list(second) == ["7"]
