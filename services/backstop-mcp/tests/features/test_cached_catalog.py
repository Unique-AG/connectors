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
from collections.abc import AsyncGenerator, Callable, Generator, Mapping
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Protocol, cast

import httpx
import pytest
import respx
from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.dependencies import get_backstop_config
from backstop_mcp.features.activity_tags import ActivityTagsService, get_activity_tags_service
from backstop_mcp.features.cached_catalog import CachedCatalog
from backstop_mcp.features.custom_fields import (
    CustomFieldGroupsService,
    CustomFieldsService,
    get_custom_field_groups_service,
    get_custom_fields_service,
)
from backstop_mcp.features.system_users import SystemUsersService, get_system_users_service
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
    # Takes `caching_enabled`, because both modes ship: the protocol below is tested with it on,
    # while a deployment picks per feature via `BACKSTOP_*_CACHE_ENABLED` (custom-field on,
    # activity tags and system users off).
    build: Callable[[bool], _Catalog]

    def service(self, *, caching_enabled: bool = True) -> _Catalog:
        return self.build(caching_enabled)

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
        build=lambda caching: cast(
            "_Catalog",
            ActivityTagsService.with_ttl_minutes(ttl_minutes=60, caching_enabled=caching),
        ),
    ),
    _CatalogUnderTest(
        slug="custom-field-groups",
        path="/custom-field-groups",
        resource_type="custom-field-groups",
        build=lambda caching: cast(
            "_Catalog",
            CustomFieldGroupsService.with_ttl_minutes(ttl_minutes=60, caching_enabled=caching),
        ),
    ),
    _CatalogUnderTest(
        slug="system-users",
        path="/system-users",
        resource_type="system-users",
        build=lambda caching: cast(
            "_Catalog",
            SystemUsersService.with_ttl_minutes(ttl_minutes=60, caching_enabled=caching),
        ),
    ),
    _CatalogUnderTest(
        slug="custom-field-definitions",
        path="/custom-field-definitions",
        resource_type="custom-field-definitions",
        required_attributes={"entityType": "OrganizationBean", "fieldType": "text"},
        build=lambda caching: cast(
            "_Catalog",
            CustomFieldsService.with_ttl_minutes(ttl_minutes=60, caching_enabled=caching),
        ),
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


@pytest.mark.parametrize("catalog", _CATALOGS, ids=[case.slug for case in _CATALOGS])
class TestCachingDisabled:
    """`caching_enabled=False` — what every provider in a feature's `dependencies.py` passes.

    The mechanisms above are all still constructed; none of them is consulted. What must hold is
    that nothing survives a call (so no read is ever answered from memory and `"stale"` cannot be
    returned) while concurrent callers still collapse onto one walk, since that coalescing is
    deduplication rather than caching and switching it off would multiply the load the
    `catalog_fetch_duration_seconds` histogram exists to measure.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_every_get_walks_backstop_again(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("off-no-reuse")
        service = catalog.service(caching_enabled=False)
        route = respx.get(f"{base_url}{catalog.path}").mock(
            side_effect=[
                catalog.page(("1", "First Walk")),
                catalog.page(("2", "Second Walk")),
            ]
        )

        first, first_cache = await service.get(clients(base_url))
        second, second_cache = await service.get(clients(base_url))

        assert route.call_count == 2
        assert first_cache == "ok"
        assert second_cache == "ok"
        assert _names(first) == ["First Walk"]
        assert _names(second) == ["Second Walk"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_fetch_propagates_instead_of_serving_the_last_good_catalog(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        """Serve-stale needs something held, and this mode holds nothing."""
        base_url = catalog.base_url("off-no-stale")
        service = catalog.service(caching_enabled=False)
        respx.get(f"{base_url}{catalog.path}").mock(
            side_effect=[
                catalog.page(("1", "Good Walk")),
                httpx.ConnectError("backstop down"),
            ]
        )

        _first, first_cache = await service.get(clients(base_url))
        assert first_cache == "ok"

        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_gets_still_coalesce_onto_one_walk(
        self, catalog: _CatalogUnderTest, clients: ClientBuilder
    ) -> None:
        base_url = catalog.base_url("off-single-flight")
        service = catalog.service(caching_enabled=False)
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocked(_request: httpx.Request) -> httpx.Response:
            started.set()
            await release.wait()
            return catalog.page(("7", "Shared Walk"))

        route = respx.get(f"{base_url}{catalog.path}").mock(side_effect=blocked)

        gets = [asyncio.create_task(service.get(clients(base_url))) for _ in range(3)]
        await _join_in_flight(started, release)
        results = await asyncio.wait_for(asyncio.gather(*gets), timeout=5)

        assert route.call_count == 1
        assert [_names(entries) for entries, _cache in results] == [["Shared Walk"]] * 3


class _StubHistogram:
    """Stands in for either catalog histogram, capturing what each record carried."""

    def __init__(self) -> None:
        self.records: list[tuple[float, dict[str, object]]] = []

    def record(self, amount: float, attributes: dict[str, object] | None = None) -> None:
        self.records.append((amount, dict(attributes or {})))

    def labels(self, key: str) -> list[object]:
        return [attributes[key] for _duration, attributes in self.records]


class TestFetchTelemetry:
    """`catalog_fetch_duration_seconds` — the evidence for whether to re-enable caching.

    Its `_count` has to be the number of walks Backstop actually saw, not the number of `get`
    calls, or the histogram answers a different question than the one the caching decision asks.
    One catalog is enough: the instrument is recorded in `CachedCatalog` itself, which all four
    share.
    """

    _CATALOG: ClassVar[_CatalogUnderTest] = _CATALOGS[0]

    @staticmethod
    def _stub(monkeypatch: pytest.MonkeyPatch) -> _StubHistogram:
        histogram = _StubHistogram()
        # Patched where it is used, not on `metrics`: the instrument is bound into
        # `cached_catalog` at import, so replacing the origin leaves that reference in place.
        monkeypatch.setattr(
            "backstop_mcp.features.cached_catalog.CATALOG_FETCH_DURATION", histogram
        )
        return histogram

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_successful_walk_records_its_duration_under_the_catalog_name(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        base_url = self._CATALOG.base_url("metric-ok")
        service = self._CATALOG.service(caching_enabled=False)
        self._CATALOG.route(base_url, ("7", "Measured Entry"))

        await service.get(clients(base_url))

        assert len(histogram.records) == 1
        duration, attributes = histogram.records[0]
        assert duration >= 0
        assert attributes == {"catalog": "activity-tag", "outcome": "ok"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_walk_is_recorded_as_an_error(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        base_url = self._CATALOG.base_url("metric-error")
        service = self._CATALOG.service(caching_enabled=False)
        respx.get(f"{base_url}{self._CATALOG.path}").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))

        assert [attributes["outcome"] for _duration, attributes in histogram.records] == ["error"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_cancelled_walk_is_recorded_as_cancelled_rather_than_dropped(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Otherwise a cancelled walk inflates neither count nor buckets and goes unseen."""
        histogram = self._stub(monkeypatch)
        base_url = self._CATALOG.base_url("metric-cancelled")
        service = self._CATALOG.service(caching_enabled=False)
        started = asyncio.Event()

        async def never_answers(_request: httpx.Request) -> httpx.Response:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        respx.get(f"{base_url}{self._CATALOG.path}").mock(side_effect=never_answers)

        task = asyncio.create_task(service.get(clients(base_url)))
        await asyncio.wait_for(started.wait(), timeout=5)
        _ = task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert [attributes["outcome"] for _duration, attributes in histogram.records] == [
            "cancelled"
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_cached_read_records_nothing_so_the_count_is_walks_not_gets(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        base_url = self._CATALOG.base_url("metric-cached")
        service = self._CATALOG.service(caching_enabled=True)
        self._CATALOG.route(base_url, ("7", "Measured Entry"))

        await service.get(clients(base_url))
        await service.get(clients(base_url))

        assert len(histogram.records) == 1


class TestGetDemandTelemetry:
    """`catalog_get_duration_seconds` — the other half of the pair, and the counterfactual.

    Its `_count` must be *demand*: one record per `get`, whoever answered it. That is what makes
    it the "walks there would be with no cache" number the caching decision compares against
    `catalog_fetch_duration_seconds_count`. The `served` label is what then says which mechanism
    absorbed the difference, so each of its values is pinned to the situation that produces it.
    """

    _CATALOG: ClassVar[_CatalogUnderTest] = _CATALOGS[0]

    @staticmethod
    def _stub(monkeypatch: pytest.MonkeyPatch) -> _StubHistogram:
        histogram = _StubHistogram()
        monkeypatch.setattr("backstop_mcp.features.cached_catalog.CATALOG_GET_DURATION", histogram)
        return histogram

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_walk_this_caller_owned_is_served_by_backstop(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        base_url = self._CATALOG.base_url("demand-backstop")
        service = self._CATALOG.service(caching_enabled=False)
        self._CATALOG.route(base_url, ("7", "Walked Entry"))

        await service.get(clients(base_url))

        assert histogram.labels("served") == ["backstop"]
        assert histogram.labels("catalog") == ["activity-tag"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_ttl_hit_is_served_by_cache_and_still_counts_as_demand(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point: two `get`s, one walk, and the histogram sees both `get`s."""
        histogram = self._stub(monkeypatch)
        base_url = self._CATALOG.base_url("demand-cache")
        service = self._CATALOG.service(caching_enabled=True)
        route = self._CATALOG.route(base_url, ("7", "Cached Entry"))

        await service.get(clients(base_url))
        await service.get(clients(base_url))

        assert route.call_count == 1
        assert histogram.labels("served") == ["backstop", "cache"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_waiters_on_one_walk_are_served_by_coalescing(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With caching off this is the only mechanism removing load, so it is labelled apart."""
        histogram = self._stub(monkeypatch)
        base_url = self._CATALOG.base_url("demand-coalesced")
        service = self._CATALOG.service(caching_enabled=False)
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocked(_request: httpx.Request) -> httpx.Response:
            started.set()
            await release.wait()
            return self._CATALOG.page(("7", "Shared Entry"))

        route = respx.get(f"{base_url}{self._CATALOG.path}").mock(side_effect=blocked)

        gets = [asyncio.create_task(service.get(clients(base_url))) for _ in range(3)]
        await _join_in_flight(started, release)
        await asyncio.wait_for(asyncio.gather(*gets), timeout=5)

        assert route.call_count == 1
        served = histogram.labels("served")
        assert len(served) == 3
        assert served.count("backstop") == 1
        assert served.count("coalesced") == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_refresh_that_fell_back_to_the_previous_catalog_is_served_stale(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        base_url = self._CATALOG.base_url("demand-stale")
        service = self._CATALOG.service(caching_enabled=True)
        respx.get(f"{base_url}{self._CATALOG.path}").mock(
            side_effect=[
                self._CATALOG.page(("7", "Good Entry")),
                httpx.ConnectError("backstop down"),
            ]
        )

        await service.get(clients(base_url))
        _entries, freshness = await service.get(clients(base_url), refresh=True)

        assert freshness == "stale"
        assert histogram.labels("served") == ["backstop", "stale"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_get_is_still_demand(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caller that got nothing still asked, so it belongs in the counterfactual."""
        histogram = self._stub(monkeypatch)
        base_url = self._CATALOG.base_url("demand-error")
        service = self._CATALOG.service(caching_enabled=False)
        respx.get(f"{base_url}{self._CATALOG.path}").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))

        assert histogram.labels("served") == ["error"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_cancelled_get_is_recorded_as_cancelled(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        base_url = self._CATALOG.base_url("demand-cancelled")
        service = self._CATALOG.service(caching_enabled=False)
        started = asyncio.Event()

        async def never_answers(_request: httpx.Request) -> httpx.Response:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        respx.get(f"{base_url}{self._CATALOG.path}").mock(side_effect=never_answers)

        task = asyncio.create_task(service.get(clients(base_url)))
        await asyncio.wait_for(started.wait(), timeout=5)
        _ = task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert histogram.labels("served") == ["cancelled"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_demand_exceeds_walks_by_exactly_what_the_cache_absorbed(
        self, clients: ClientBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The subtraction the two histograms exist to support, on one concrete run."""
        demand = self._stub(monkeypatch)
        walks = _StubHistogram()
        monkeypatch.setattr("backstop_mcp.features.cached_catalog.CATALOG_FETCH_DURATION", walks)
        base_url = self._CATALOG.base_url("demand-vs-walks")
        service = self._CATALOG.service(caching_enabled=True)
        self._CATALOG.route(base_url, ("7", "Cached Entry"))

        for _ in range(5):
            await service.get(clients(base_url))

        assert len(demand.records) == 5
        assert len(walks.records) == 1
        assert demand.labels("served").count("cache") == len(demand.records) - len(walks.records)


class TestCachingFlagsComeFromTheEnvironment:
    """Turning one catalog's cache on is an env var, not a deploy of new code.

    The flag is per feature and mirrors the TTL knob it governs, so the two custom-field catalogs
    share one — they already share `custom_field_schema_ttl_minutes`. Asserted through the real
    providers because the wiring is the whole feature: a flag that never reaches `CachedCatalog`
    reads exactly like a working one.
    """

    _PROVIDERS: ClassVar[tuple[Callable[[], _Catalog], ...]] = (
        cast("Callable[[], _Catalog]", get_activity_tags_service),
        cast("Callable[[], _Catalog]", get_system_users_service),
        cast("Callable[[], _Catalog]", get_custom_fields_service),
        cast("Callable[[], _Catalog]", get_custom_field_groups_service),
    )
    _FLAGS: ClassVar[tuple[str, ...]] = (
        "BACKSTOP_ACTIVITY_TAG_CACHE_ENABLED",
        "BACKSTOP_SYSTEM_USER_CACHE_ENABLED",
        "BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED",
    )

    @pytest.fixture(autouse=True)
    def _fresh_providers(self) -> Generator[None]:
        """Providers are `lru_cache(maxsize=1)`, so each case needs them rebuilt — and so does
        whatever runs next, since a service built here would otherwise outlive this test.

        `get_backstop_config` is cleared with them: it caches the very env vars under test.
        """
        self._clear_caches()
        yield
        self._clear_caches()

    @staticmethod
    def _clear_caches() -> None:
        get_backstop_config.cache_clear()
        for provider in (
            get_activity_tags_service,
            get_system_users_service,
            get_custom_fields_service,
            get_custom_field_groups_service,
        ):
            provider.cache_clear()

    @staticmethod
    def _enabled(service: _Catalog) -> bool:
        return service._caching_enabled  # pyright: ignore[reportPrivateUsage]

    def test_catalogs_ship_with_custom_field_cache_on_and_the_rest_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for flag in self._FLAGS:
            monkeypatch.delenv(flag, raising=False)

        tags, users, fields, groups = (provider() for provider in self._PROVIDERS)
        assert self._enabled(tags) is False
        assert self._enabled(users) is False
        assert self._enabled(fields) is True
        assert self._enabled(groups) is True

    def test_a_flag_enables_only_its_own_feature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The point of per-feature flags: one catalog's numbers cannot commit the others."""
        for flag in self._FLAGS:
            monkeypatch.delenv(flag, raising=False)
        monkeypatch.setenv("BACKSTOP_ACTIVITY_TAG_CACHE_ENABLED", "true")
        monkeypatch.setenv("BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED", "false")

        tags, users, fields, groups = (provider() for provider in self._PROVIDERS)

        assert self._enabled(tags) is True
        assert self._enabled(users) is False
        assert self._enabled(fields) is False
        assert self._enabled(groups) is False

    def test_the_custom_field_flag_covers_both_of_that_features_catalogs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for flag in self._FLAGS:
            monkeypatch.delenv(flag, raising=False)
        monkeypatch.setenv("BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED", "false")

        assert self._enabled(cast("_Catalog", get_custom_fields_service())) is False
        assert self._enabled(cast("_Catalog", get_custom_field_groups_service())) is False

        self._clear_caches()
        monkeypatch.setenv("BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED", "true")

        # Cast for the same reason `_CATALOGS` does: `CachedCatalog[T]` is invariant in `T`, so
        # the concrete services share no supertype.
        assert self._enabled(cast("_Catalog", get_custom_fields_service())) is True
        assert self._enabled(cast("_Catalog", get_custom_field_groups_service())) is True

    def test_an_enabled_catalog_still_takes_its_ttl_from_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The flag decides whether the TTL is consulted, not what it is."""
        monkeypatch.setenv("BACKSTOP_ACTIVITY_TAG_CACHE_ENABLED", "true")
        monkeypatch.setenv("BACKSTOP_ACTIVITY_TAG_TTL_MINUTES", "90")

        service = get_activity_tags_service()

        assert service._freshness.duration == timedelta(minutes=90)  # pyright: ignore[reportPrivateUsage]
