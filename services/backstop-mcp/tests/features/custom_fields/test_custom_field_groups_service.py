import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.custom_fields import CustomFieldGroupsService
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]


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


def _service(*, ttl_minutes: int = 60) -> CustomFieldGroupsService:
    return CustomFieldGroupsService.with_ttl_minutes(ttl_minutes=ttl_minutes)


class TestInMemoryTtl:
    """The in-memory catalog is a cache with a TTL, not a permanent record."""

    @staticmethod
    def _age_past_ttl(service: CustomFieldGroupsService) -> None:
        past = datetime.now(UTC) - timedelta(minutes=90)
        service._freshness.mark(past)  # pyright: ignore[reportPrivateUsage]

    @staticmethod
    def _groups_route(base_url: str, name: str, group_id: str = "1") -> respx.Route:
        return respx.get(f"{base_url}/custom-field-groups").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            group_id,
                            "custom-field-groups",
                            name=name,
                            fullPathName=[name],
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_get_within_ttl_does_not_call_backstop(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ttl-fresh"
        service = _service()
        route = self._groups_route(base_url, "Cached Group")

        first, first_cache = await service.get(clients(base_url))
        second, second_cache = await service.get(clients(base_url))

        assert route.call_count == 1
        assert first_cache == "ok"
        assert second_cache == "ok"
        assert [group.name for group in first.values()] == ["Cached Group"]
        assert [group.name for group in second.values()] == ["Cached Group"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_past_ttl_fetches_again(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-expired"
        service = _service()
        route = respx.get(f"{base_url}/custom-field-groups").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [
                            resource(
                                "old-1",
                                "custom-field-groups",
                                name="Stale Group",
                                fullPathName=["Stale Group"],
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
                                "custom-field-groups",
                                name="Fresh Group",
                                fullPathName=["Fresh Group"],
                            )
                        ],
                        "links": {"next": None},
                    },
                ),
            ]
        )

        await service.get(clients(base_url))
        self._age_past_ttl(service)
        groups, cache = await service.get(clients(base_url))

        assert route.call_count == 2
        assert cache == "ok"
        assert [group.name for group in groups.values()] == ["Fresh Group"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_fetches_even_when_fresh(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-refresh"
        service = _service()
        route = respx.get(f"{base_url}/custom-field-groups").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [
                            resource(
                                "old-1",
                                "custom-field-groups",
                                name="Cached Group",
                                fullPathName=["Cached Group"],
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
                                "custom-field-groups",
                                name="Refreshed Group",
                                fullPathName=["Refreshed Group"],
                            )
                        ],
                        "links": {"next": None},
                    },
                ),
            ]
        )

        await service.get(clients(base_url))
        groups, cache = await service.get(clients(base_url), refresh=True)

        assert route.call_count == 2
        assert cache == "ok"
        assert [group.name for group in groups.values()] == ["Refreshed Group"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_warm_read_does_not_queue_behind_an_in_flight_refresh(
        self, clients: ClientBuilder
    ) -> None:
        """A fresh `get()` must not block on the lock a refresh is holding."""
        base_url = f"{BASE_URL}/ttl-warm-read-not-blocked"
        service = _service()
        self._groups_route(base_url, "Warm Group")
        await service.get(clients(base_url))

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_groups(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(200, json={"data": [], "links": {"next": None}})

        respx.get(f"{base_url}/custom-field-groups").mock(side_effect=blocked_groups)

        refresh_task = asyncio.create_task(service.get(clients(base_url), refresh=True))
        await asyncio.wait_for(refresh_started.wait(), timeout=5)

        groups, cache = await asyncio.wait_for(service.get(clients(base_url)), timeout=1)
        assert cache == "ok"
        assert [group.name for group in groups.values()] == ["Warm Group"]

        release_refresh.set()
        _ = await asyncio.wait_for(refresh_task, timeout=5)

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_cold_gets_produce_one_walk(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-single-flight"
        service = _service()
        route = self._groups_route(base_url, "Fresh Group")
        client = clients(base_url)

        results = await asyncio.gather(
            service.get(client),
            service.get(client),
            service.get(client),
        )

        assert route.call_count == 1
        for groups, cache in results:
            assert cache == "ok"
            assert [group.name for group in groups.values()] == ["Fresh Group"]

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
        self._groups_route(base_url, "Cached Group")
        await service.get(client)

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_groups(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "2",
                            "custom-field-groups",
                            name="Refreshed Group",
                            fullPathName=["Refreshed Group"],
                        )
                    ],
                    "links": {"next": None},
                },
            )

        route = respx.get(f"{base_url}/custom-field-groups").mock(side_effect=blocked_groups)

        warm_calls = route.call_count
        results = await asyncio.gather(
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            self._join_in_flight(refresh_started, release_refresh),
        )

        assert route.call_count == warm_calls + 1
        for groups, cache in results[:3]:
            assert cache == "ok"
            assert [group.name for group in groups.values()] == ["Refreshed Group"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_failed_refreshes_share_stale(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-refresh-fail-single-flight"
        service = _service()
        client = clients(base_url)
        self._groups_route(base_url, "Cached Group")
        await service.get(client)

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_failure(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            raise httpx.ConnectError("backstop down")

        route = respx.get(f"{base_url}/custom-field-groups").mock(side_effect=blocked_failure)

        warm_calls = route.call_count
        results = await asyncio.gather(
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            service.get(client, refresh=True),
            self._join_in_flight(refresh_started, release_refresh),
        )

        assert route.call_count == warm_calls + 1
        for groups, cache in results[:3]:
            assert cache == "stale"
            assert [group.name for group in groups.values()] == ["Cached Group"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_fetch_with_a_cache_keeps_stale(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-refresh-fails"
        service = _service()
        self._groups_route(base_url, "Stale Group", group_id="old-1")
        await service.get(clients(base_url))
        self._age_past_ttl(service)

        respx.get(f"{base_url}/custom-field-groups").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        groups, cache = await service.get(clients(base_url))

        assert cache == "stale"
        assert [group.name for group in groups.values()] == ["Stale Group"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_refresh_restamps_ttl_so_the_next_get_does_not_refetch(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ttl-stale-cooldown"
        service = _service()
        self._groups_route(base_url, "Stale Group", group_id="old-1")
        await service.get(clients(base_url))
        self._age_past_ttl(service)

        failed = respx.get(f"{base_url}/custom-field-groups").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        first, first_cache = await service.get(clients(base_url))
        calls_after_failure = failed.call_count
        second, second_cache = await service.get(clients(base_url))

        assert calls_after_failure >= 1
        assert failed.call_count == calls_after_failure
        assert first_cache == "stale"
        assert second_cache == "ok"
        assert [group.name for group in first.values()] == ["Stale Group"]
        assert [group.name for group in second.values()] == ["Stale Group"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_cancelled_fetch_unblocks_waiters(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-cancel-waiters"
        service = _service()
        client = clients(base_url)
        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_groups(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(200, json={"data": [], "links": {"next": None}})

        respx.get(f"{base_url}/custom-field-groups").mock(side_effect=blocked_groups)

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

        self._groups_route(base_url, "After Cancel")
        groups, cache = await asyncio.wait_for(service.get(client), timeout=5)
        assert cache == "ok"
        assert [group.name for group in groups.values()] == ["After Cancel"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_done_in_flight_future_does_not_block_the_next_get(
        self, clients: ClientBuilder
    ) -> None:
        """If unpinning is skipped, a finished future must not pin the catalog forever."""
        base_url = f"{BASE_URL}/ttl-stale-in-flight"
        service = _service()
        done = asyncio.get_running_loop().create_future()
        done.set_exception(RuntimeError("custom-field group catalog fetch was cancelled"))
        service._in_flight = done  # pyright: ignore[reportPrivateUsage]
        route = self._groups_route(base_url, "Recovered Group")

        groups, cache = await service.get(clients(base_url))

        assert cache == "ok"
        assert [group.name for group in groups.values()] == ["Recovered Group"]
        assert route.call_count == 1
        assert service._in_flight is None  # pyright: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_fetch_with_no_cache_raises(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-cold-failure"
        service = _service()
        respx.get(f"{base_url}/custom-field-groups").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))
