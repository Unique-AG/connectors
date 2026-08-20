import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.activity_tags import ActivityTagsService
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]

_LIVE_TAG_ID = "474963"


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


def _service(*, ttl_minutes: int = 60) -> ActivityTagsService:
    return ActivityTagsService.with_ttl_minutes(ttl_minutes=ttl_minutes)


class TestInMemoryTtl:
    """The in-memory catalog is a cache with a TTL, not a permanent record."""

    @staticmethod
    def _age_past_ttl(service: ActivityTagsService) -> None:
        past = datetime.now(UTC) - timedelta(minutes=90)
        service._freshness.mark(past)  # pyright: ignore[reportPrivateUsage]

    @staticmethod
    def _tags_route(
        base_url: str,
        name: str,
        tag_id: str = _LIVE_TAG_ID,
        *,
        quantity_tagged: int = 12,
        viewable: bool = True,
    ) -> respx.Route:
        return respx.get(f"{base_url}/activity-tags").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            tag_id,
                            "activity-tags",
                            name=name,
                            quantityTagged=quantity_tagged,
                            viewable=viewable,
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_first_fetch_caches_by_id_and_second_get_does_not_rehit(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ttl-fresh"
        service = _service()
        route = self._tags_route(base_url, "Quarterly Review")

        first, first_cache = await service.get(clients(base_url))
        second, second_cache = await service.get(clients(base_url))

        assert route.call_count == 1
        assert first_cache == "ok"
        assert second_cache == "ok"
        assert first[_LIVE_TAG_ID].name == "Quarterly Review"
        assert first[_LIVE_TAG_ID].quantity_tagged == 12
        assert first[_LIVE_TAG_ID].viewable is True
        assert second[_LIVE_TAG_ID].name == "Quarterly Review"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_past_ttl_fetches_again(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-expired"
        service = _service()
        route = respx.get(f"{base_url}/activity-tags").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [
                            resource(
                                "old-1",
                                "activity-tags",
                                name="Stale Tag",
                                quantityTagged=1,
                                viewable=True,
                            )
                        ],
                        "links": {"next": None},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [
                            resource(
                                "new-1",
                                "activity-tags",
                                name="Fresh Tag",
                                quantityTagged=4,
                                viewable=True,
                            )
                        ],
                        "links": {"next": None},
                    },
                ),
            ]
        )

        await service.get(clients(base_url))
        self._age_past_ttl(service)
        tags, cache = await service.get(clients(base_url))

        assert route.call_count == 2
        assert cache == "ok"
        assert [tag.name for tag in tags.values()] == ["Fresh Tag"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_fetches_even_when_fresh(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-refresh"
        service = _service()
        route = respx.get(f"{base_url}/activity-tags").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [
                            resource(
                                "old-1",
                                "activity-tags",
                                name="Cached Tag",
                                quantityTagged=1,
                                viewable=True,
                            )
                        ],
                        "links": {"next": None},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [
                            resource(
                                "new-1",
                                "activity-tags",
                                name="Refreshed Tag",
                                quantityTagged=2,
                                viewable=True,
                            )
                        ],
                        "links": {"next": None},
                    },
                ),
            ]
        )

        await service.get(clients(base_url))
        tags, cache = await service.get(clients(base_url), refresh=True)

        assert route.call_count == 2
        assert cache == "ok"
        assert [tag.name for tag in tags.values()] == ["Refreshed Tag"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_warm_read_does_not_queue_behind_an_in_flight_refresh(
        self, clients: ClientBuilder
    ) -> None:
        """A fresh `get()` must not block on the lock a refresh is holding."""
        base_url = f"{BASE_URL}/ttl-warm-read-not-blocked"
        service = _service()
        self._tags_route(base_url, "Warm Tag")
        await service.get(clients(base_url))

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_tags(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(200, json={"data": [], "links": {"next": None}})

        respx.get(f"{base_url}/activity-tags").mock(side_effect=blocked_tags)

        refresh_task = asyncio.create_task(service.get(clients(base_url), refresh=True))
        await asyncio.wait_for(refresh_started.wait(), timeout=5)

        tags, cache = await asyncio.wait_for(service.get(clients(base_url)), timeout=1)
        assert cache == "ok"
        assert tags[_LIVE_TAG_ID].name == "Warm Tag"

        release_refresh.set()
        _ = await asyncio.wait_for(refresh_task, timeout=5)

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_cold_gets_produce_one_walk(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-single-flight"
        service = _service()
        route = self._tags_route(base_url, "Fresh Tag")
        client = clients(base_url)

        results = await asyncio.gather(
            service.get(client),
            service.get(client),
            service.get(client),
        )

        assert route.call_count == 1
        for tags, cache in results:
            assert cache == "ok"
            assert tags[_LIVE_TAG_ID].name == "Fresh Tag"

    @staticmethod
    async def _join_in_flight(started: asyncio.Event, release: asyncio.Event) -> None:
        """Unblock Backstop only after sibling refresh tasks have had a turn to join."""
        await started.wait()
        for _ in range(20):
            await asyncio.sleep(0)
        release.set()

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_refreshes_produce_one_walk(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-refresh-single-flight"
        service = _service()
        client = clients(base_url)
        self._tags_route(base_url, "Cached Tag")
        await service.get(client)

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_tags(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "2",
                            "activity-tags",
                            name="Refreshed Tag",
                            quantityTagged=3,
                            viewable=True,
                        )
                    ],
                    "links": {"next": None},
                },
            )

        route = respx.get(f"{base_url}/activity-tags").mock(side_effect=blocked_tags)

        warm_calls = route.call_count
        results = await asyncio.gather(
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            self._join_in_flight(refresh_started, release_refresh),
        )

        assert route.call_count == warm_calls + 1
        for tags, cache in results[:3]:
            assert cache == "ok"
            assert [tag.name for tag in tags.values()] == ["Refreshed Tag"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_failed_refreshes_share_stale(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-refresh-fail-single-flight"
        service = _service()
        client = clients(base_url)
        self._tags_route(base_url, "Cached Tag")
        await service.get(client)

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_failure(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            raise httpx.ConnectError("backstop down")

        route = respx.get(f"{base_url}/activity-tags").mock(side_effect=blocked_failure)

        warm_calls = route.call_count
        results = await asyncio.gather(
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            self._join_in_flight(refresh_started, release_refresh),
        )

        assert route.call_count == warm_calls + 1
        for tags, cache in results[:3]:
            assert cache == "stale"
            assert tags[_LIVE_TAG_ID].name == "Cached Tag"

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_fetch_with_a_cache_keeps_stale(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-refresh-fails"
        service = _service()
        self._tags_route(base_url, "Stale Tag", tag_id="old-1")
        await service.get(clients(base_url))
        self._age_past_ttl(service)

        respx.get(f"{base_url}/activity-tags").mock(side_effect=httpx.ConnectError("backstop down"))

        tags, cache = await service.get(clients(base_url))

        assert cache == "stale"
        assert tags["old-1"].name == "Stale Tag"

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_refresh_restamps_ttl_so_the_next_get_does_not_refetch(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ttl-stale-cooldown"
        service = _service()
        self._tags_route(base_url, "Stale Tag", tag_id="old-1")
        await service.get(clients(base_url))
        self._age_past_ttl(service)

        failed = respx.get(f"{base_url}/activity-tags").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        first, first_cache = await service.get(clients(base_url))
        calls_after_failure = failed.call_count
        second, second_cache = await service.get(clients(base_url))

        assert calls_after_failure >= 1
        assert failed.call_count == calls_after_failure
        assert first_cache == "stale"
        assert second_cache == "ok"
        assert first["old-1"].name == "Stale Tag"
        assert second["old-1"].name == "Stale Tag"

    @pytest.mark.asyncio
    @respx.mock
    async def test_cancelled_fetch_unblocks_waiters(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-cancel-waiters"
        service = _service()
        client = clients(base_url)
        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_tags(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(200, json={"data": [], "links": {"next": None}})

        respx.get(f"{base_url}/activity-tags").mock(side_effect=blocked_tags)

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

        self._tags_route(base_url, "After Cancel")
        tags, cache = await asyncio.wait_for(service.get(client), timeout=5)
        assert cache == "ok"
        assert tags[_LIVE_TAG_ID].name == "After Cancel"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_done_in_flight_future_does_not_block_the_next_get(
        self, clients: ClientBuilder
    ) -> None:
        """If unpinning is skipped, a finished future must not pin the catalog forever."""
        base_url = f"{BASE_URL}/ttl-stale-in-flight"
        service = _service()
        done = asyncio.get_running_loop().create_future()
        done.set_exception(RuntimeError("activity-tag catalog fetch was cancelled"))
        service._in_flight = done  # pyright: ignore[reportPrivateUsage]
        route = self._tags_route(base_url, "Recovered Tag")

        tags, cache = await service.get(clients(base_url))

        assert cache == "ok"
        assert tags[_LIVE_TAG_ID].name == "Recovered Tag"
        assert route.call_count == 1
        assert service._in_flight is None  # pyright: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_fetch_with_no_cache_raises(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-cold-failure"
        service = _service()
        respx.get(f"{base_url}/activity-tags").mock(side_effect=httpx.ConnectError("backstop down"))

        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))
