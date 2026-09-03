"""The TTL / single-flight / serve-stale protocol on `CachedValue`.

Catalog services compose this; they are not a cache. Feature-specific projection stays in
each feature's own test file. Wiring that a service `get()` hits Backstop once is
`tests/features/test_cached_catalog.py`.
"""

import asyncio
import gc
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest

from backstop_mcp.caching import CachedValue, CacheSource

type _Fetch = Callable[[], Awaitable[dict[str, str]]]


def _cache(
    *,
    caching_enabled: bool = True,
    serve_stale: bool = True,
    ttl: timedelta = timedelta(minutes=60),
    name: str = "test-cache",
    on_load: Callable[[CacheSource], None] | None = None,
) -> CachedValue[dict[str, str]]:
    return CachedValue(
        ttl=ttl,
        snapshot=dict,
        name=name,
        log_prefix="test_cache",
        caching_enabled=caching_enabled,
        serve_stale=serve_stale,
        on_load=on_load,
    )


def _age_past_ttl(cache: CachedValue[dict[str, str]]) -> None:
    past = datetime.now(UTC) - timedelta(minutes=90)
    cache._freshness.mark(past)  # pyright: ignore[reportPrivateUsage]


def _fetch_returning(payload: dict[str, str]) -> tuple[_Fetch, list[int]]:
    calls = [0]

    async def fetch() -> dict[str, str]:
        calls[0] += 1
        return dict(payload)

    return fetch, calls


def _fetch_sequence(*payloads: dict[str, str] | BaseException) -> tuple[_Fetch, list[int]]:
    remaining = list(payloads)
    calls = [0]

    async def fetch() -> dict[str, str]:
        calls[0] += 1
        next_result = remaining.pop(0)
        if isinstance(next_result, BaseException):
            raise next_result
        return dict(next_result)

    return fetch, calls


async def _join_in_flight(started: asyncio.Event, release: asyncio.Event) -> None:
    """Unblock the fetch only after sibling refresh tasks have had a turn to join."""
    await started.wait()
    for _ in range(20):
        await asyncio.sleep(0)
    release.set()


class TestInMemoryTtl:
    @pytest.mark.asyncio
    async def test_first_fetch_caches_and_second_get_does_not_refetch(self) -> None:
        cache = _cache()
        fetch, calls = _fetch_returning({"7": "Cached Entry"})

        first, first_cache = await cache.get(fetch)
        second, second_cache = await cache.get(fetch)

        assert calls[0] == 1
        assert first_cache == "ok"
        assert second_cache == "ok"
        assert first == {"7": "Cached Entry"}
        assert second == {"7": "Cached Entry"}

    @pytest.mark.asyncio
    async def test_get_past_ttl_fetches_again(self) -> None:
        cache = _cache()
        fetch, calls = _fetch_sequence({"old": "Stale Entry"}, {"new": "Fresh Entry"})

        await cache.get(fetch)
        _age_past_ttl(cache)
        value, freshness = await cache.get(fetch)

        assert calls[0] == 2
        assert freshness == "ok"
        assert value == {"new": "Fresh Entry"}

    @pytest.mark.asyncio
    async def test_refresh_fetches_even_when_fresh(self) -> None:
        cache = _cache()
        fetch, calls = _fetch_sequence({"old": "Cached Entry"}, {"new": "Refreshed Entry"})

        await cache.get(fetch)
        value, freshness = await cache.get(fetch, refresh=True)

        assert calls[0] == 2
        assert freshness == "ok"
        assert value == {"new": "Refreshed Entry"}

    @pytest.mark.asyncio
    async def test_a_warm_read_does_not_queue_behind_an_in_flight_refresh(self) -> None:
        cache = _cache()
        warm, _calls = _fetch_returning({"7": "Warm Entry"})
        await cache.get(warm)

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked() -> dict[str, str]:
            refresh_started.set()
            await release_refresh.wait()
            return {}

        refresh_task = asyncio.create_task(cache.get(blocked, refresh=True))
        await asyncio.wait_for(refresh_started.wait(), timeout=5)

        value, freshness = await asyncio.wait_for(cache.get(warm), timeout=1)
        assert freshness == "ok"
        assert value == {"7": "Warm Entry"}

        release_refresh.set()
        _ = await asyncio.wait_for(refresh_task, timeout=5)

    @pytest.mark.asyncio
    async def test_concurrent_cold_gets_produce_one_fetch(self) -> None:
        cache = _cache()
        fetch, calls = _fetch_returning({"7": "Fresh Entry"})

        results = await asyncio.gather(cache.get(fetch), cache.get(fetch), cache.get(fetch))

        assert calls[0] == 1
        for value, freshness in results:
            assert freshness == "ok"
            assert value == {"7": "Fresh Entry"}

    @pytest.mark.asyncio
    async def test_concurrent_refreshes_produce_one_fetch(self) -> None:
        cache = _cache()
        warm, _warm_calls = _fetch_returning({"7": "Cached Entry"})
        await cache.get(warm)

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()
        calls = [0]

        async def blocked() -> dict[str, str]:
            calls[0] += 1
            refresh_started.set()
            await release_refresh.wait()
            return {"2": "Refreshed Entry"}

        results = await asyncio.gather(
            cache.get(blocked, refresh=True),
            cache.get(blocked, refresh=True),
            cache.get(blocked, refresh=True),
            _join_in_flight(refresh_started, release_refresh),
        )

        assert calls[0] == 1
        for value, freshness in results[:3]:
            assert freshness == "ok"
            assert value == {"2": "Refreshed Entry"}

    @pytest.mark.asyncio
    async def test_concurrent_failed_refreshes_share_stale(self) -> None:
        cache = _cache()
        warm, _warm_calls = _fetch_returning({"7": "Cached Entry"})
        await cache.get(warm)

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()
        calls = [0]

        async def blocked_failure() -> dict[str, str]:
            calls[0] += 1
            refresh_started.set()
            await release_refresh.wait()
            raise ConnectionError("backstop down")

        results = await asyncio.gather(
            cache.get(blocked_failure, refresh=True),
            cache.get(blocked_failure, refresh=True),
            cache.get(blocked_failure, refresh=True),
            _join_in_flight(refresh_started, release_refresh),
        )

        assert calls[0] == 1
        for value, freshness in results[:3]:
            assert freshness == "stale"
            assert value == {"7": "Cached Entry"}

    @pytest.mark.asyncio
    async def test_failed_fetch_with_a_cache_keeps_stale(self) -> None:
        cache = _cache()
        fetch, calls = _fetch_sequence({"old": "Stale Entry"}, ConnectionError("backstop down"))

        await cache.get(fetch)
        _age_past_ttl(cache)
        value, freshness = await cache.get(fetch)

        assert calls[0] == 2
        assert freshness == "stale"
        assert value == {"old": "Stale Entry"}

    @pytest.mark.asyncio
    async def test_failed_refresh_restamps_ttl_so_the_next_get_does_not_refetch(self) -> None:
        cache = _cache()
        fetch, calls = _fetch_sequence({"old": "Stale Entry"}, ConnectionError("backstop down"))

        await cache.get(fetch)
        _age_past_ttl(cache)

        first, first_cache = await cache.get(fetch)
        calls_after_failure = calls[0]
        second, second_cache = await cache.get(fetch)

        assert calls_after_failure == 2
        assert calls[0] == calls_after_failure
        assert first_cache == "stale"
        assert second_cache == "ok"
        assert first == {"old": "Stale Entry"}
        assert second == {"old": "Stale Entry"}

    @pytest.mark.asyncio
    async def test_cancelled_fetch_unblocks_waiters(self) -> None:
        cache = _cache()
        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked() -> dict[str, str]:
            refresh_started.set()
            await release_refresh.wait()
            return {}

        owner = asyncio.create_task(cache.get(blocked))
        await asyncio.wait_for(refresh_started.wait(), timeout=5)
        waiter = asyncio.create_task(cache.get(blocked))
        for _ in range(20):
            await asyncio.sleep(0)

        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, timeout=5)
        with pytest.raises(RuntimeError, match="cancelled"):
            await asyncio.wait_for(waiter, timeout=1)

        release_refresh.set()

        fetch, _calls = _fetch_returning({"7": "After Cancel"})
        value, freshness = await asyncio.wait_for(cache.get(fetch), timeout=5)
        assert freshness == "ok"
        assert value == {"7": "After Cancel"}

    @pytest.mark.asyncio
    async def test_a_done_in_flight_future_does_not_block_the_next_get(self) -> None:
        """If unpinning is skipped, a finished future must not pin the cache forever."""
        cache = _cache()
        done = asyncio.get_running_loop().create_future()
        done.set_exception(RuntimeError("fetch was cancelled"))
        _ = done.exception()
        cache._in_flight = done  # pyright: ignore[reportPrivateUsage]
        fetch, calls = _fetch_returning({"7": "Recovered Entry"})

        value, freshness = await cache.get(fetch)

        assert freshness == "ok"
        assert value == {"7": "Recovered Entry"}
        assert calls[0] == 1
        assert cache._in_flight is None  # pyright: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_failed_fetch_with_no_cache_raises(self) -> None:
        cache = _cache()
        fetch, _calls = _fetch_sequence(ConnectionError("backstop down"))

        with pytest.raises(ConnectionError):
            await cache.get(fetch)

    @pytest.mark.asyncio
    async def test_a_cold_fetch_failure_does_not_leave_an_unretrieved_future(self) -> None:
        """The owner re-raises the fetch error instead of awaiting the shared future.

        `set_exception` is for waiters. With none, asyncio logs "Future exception was never
        retrieved" unless the owner also retrieves it.
        """
        cache = _cache()
        fetch, _calls = _fetch_sequence(ConnectionError("backstop down"))
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
            with pytest.raises(ConnectionError):
                await cache.get(fetch)
            gc.collect()
            await asyncio.sleep(0)
            assert leaked == []
        finally:
            loop.set_exception_handler(previous)

    @pytest.mark.asyncio
    async def test_the_returned_value_is_a_copy(self) -> None:
        cache = _cache()
        fetch, _calls = _fetch_returning({"7": "Shared Entry"})

        first, _freshness = await cache.get(fetch)
        first.clear()
        second, _second = await cache.get(fetch)

        assert second == {"7": "Shared Entry"}

    @pytest.mark.asyncio
    async def test_on_load_is_called_for_a_backstop_load_and_a_stale_reuse(self) -> None:
        sources: list[CacheSource] = []
        cache = _cache(on_load=sources.append)
        fetch, _calls = _fetch_sequence({"7": "Good"}, ConnectionError("backstop down"))

        await cache.get(fetch)
        _age_past_ttl(cache)
        await cache.get(fetch)

        assert sources == ["backstop", "stale"]


class TestServeStaleDisabled:
    @pytest.mark.asyncio
    async def test_a_failed_refresh_raises_instead_of_serving_the_previous_value(self) -> None:
        cache = _cache(serve_stale=False)
        fetch, calls = _fetch_sequence({"7": "Good"}, ConnectionError("backstop down"))

        await cache.get(fetch)
        _age_past_ttl(cache)

        with pytest.raises(ConnectionError):
            await cache.get(fetch)

        assert calls[0] == 2

    @pytest.mark.asyncio
    async def test_a_failed_refresh_does_not_restamp_ttl(self) -> None:
        cache = _cache(serve_stale=False)
        fetch, calls = _fetch_sequence(
            {"7": "Good"},
            ConnectionError("first down"),
            ConnectionError("second down"),
        )

        await cache.get(fetch)
        _age_past_ttl(cache)
        with pytest.raises(ConnectionError):
            await cache.get(fetch)
        with pytest.raises(ConnectionError):
            await cache.get(fetch)

        assert calls[0] == 3


class TestCachingDisabled:
    @pytest.mark.asyncio
    async def test_every_get_fetches_again(self) -> None:
        cache = _cache(caching_enabled=False)
        fetch, calls = _fetch_sequence({"1": "First Walk"}, {"2": "Second Walk"})

        first, first_cache = await cache.get(fetch)
        second, second_cache = await cache.get(fetch)

        assert calls[0] == 2
        assert first_cache == "ok"
        assert second_cache == "ok"
        assert first == {"1": "First Walk"}
        assert second == {"2": "Second Walk"}

    @pytest.mark.asyncio
    async def test_a_failed_fetch_propagates_instead_of_serving_the_last_good_value(self) -> None:
        cache = _cache(caching_enabled=False)
        fetch, _calls = _fetch_sequence({"1": "Good Walk"}, ConnectionError("backstop down"))

        _first, first_cache = await cache.get(fetch)
        assert first_cache == "ok"

        with pytest.raises(ConnectionError):
            await cache.get(fetch)

    @pytest.mark.asyncio
    async def test_concurrent_gets_still_coalesce_onto_one_fetch(self) -> None:
        cache = _cache(caching_enabled=False)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = [0]

        async def blocked() -> dict[str, str]:
            calls[0] += 1
            started.set()
            await release.wait()
            return {"7": "Shared Walk"}

        gets = [asyncio.create_task(cache.get(blocked)) for _ in range(3)]
        await _join_in_flight(started, release)
        results = await asyncio.wait_for(asyncio.gather(*gets), timeout=5)

        assert calls[0] == 1
        assert [value for value, _freshness in results] == [{"7": "Shared Walk"}] * 3


class _StubHistogram:
    """Stands in for either catalog histogram, capturing what each record carried."""

    def __init__(self) -> None:
        self.records: list[tuple[float, dict[str, object]]] = []

    def record(self, amount: float, attributes: dict[str, object] | None = None) -> None:
        self.records.append((amount, dict(attributes or {})))

    def labels(self, key: str) -> list[object]:
        return [attributes[key] for _duration, attributes in self.records]


class TestFetchTelemetry:
    """`catalog_fetch_duration_seconds` — the evidence for whether to re-enable caching."""

    _NAME: ClassVar[str] = "test-cache"

    @staticmethod
    def _stub(monkeypatch: pytest.MonkeyPatch) -> _StubHistogram:
        histogram = _StubHistogram()
        monkeypatch.setattr("backstop_mcp.caching.cached_value.CATALOG_FETCH_DURATION", histogram)
        return histogram

    @pytest.mark.asyncio
    async def test_a_successful_fetch_records_its_duration_under_the_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        cache = _cache(caching_enabled=False, name=self._NAME)
        fetch, _calls = _fetch_returning({"7": "Measured Entry"})

        await cache.get(fetch)

        assert len(histogram.records) == 1
        duration, attributes = histogram.records[0]
        assert duration >= 0
        assert attributes == {"catalog": self._NAME, "outcome": "ok"}

    @pytest.mark.asyncio
    async def test_a_failed_fetch_is_recorded_as_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        cache = _cache(caching_enabled=False, name=self._NAME)
        fetch, _calls = _fetch_sequence(ConnectionError("backstop down"))

        with pytest.raises(ConnectionError):
            await cache.get(fetch)

        assert [attributes["outcome"] for _duration, attributes in histogram.records] == ["error"]

    @pytest.mark.asyncio
    async def test_a_cancelled_fetch_is_recorded_as_cancelled_rather_than_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        cache = _cache(caching_enabled=False, name=self._NAME)
        started = asyncio.Event()

        async def never_answers() -> dict[str, str]:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        task = asyncio.create_task(cache.get(never_answers))
        await asyncio.wait_for(started.wait(), timeout=5)
        _ = task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert [attributes["outcome"] for _duration, attributes in histogram.records] == [
            "cancelled"
        ]

    @pytest.mark.asyncio
    async def test_a_cached_read_records_nothing_so_the_count_is_fetches_not_gets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        cache = _cache(caching_enabled=True, name=self._NAME)
        fetch, _calls = _fetch_returning({"7": "Measured Entry"})

        await cache.get(fetch)
        await cache.get(fetch)

        assert len(histogram.records) == 1


class TestGetDemandTelemetry:
    """`catalog_get_duration_seconds` — the other half of the pair, and the counterfactual."""

    _NAME: ClassVar[str] = "test-cache"

    @staticmethod
    def _stub(monkeypatch: pytest.MonkeyPatch) -> _StubHistogram:
        histogram = _StubHistogram()
        monkeypatch.setattr("backstop_mcp.caching.cached_value.CATALOG_GET_DURATION", histogram)
        return histogram

    @pytest.mark.asyncio
    async def test_a_fetch_this_caller_owned_is_served_by_backstop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        cache = _cache(caching_enabled=False, name=self._NAME)
        fetch, _calls = _fetch_returning({"7": "Walked Entry"})

        await cache.get(fetch)

        assert histogram.labels("served") == ["backstop"]
        assert histogram.labels("catalog") == [self._NAME]

    @pytest.mark.asyncio
    async def test_a_ttl_hit_is_served_by_cache_and_still_counts_as_demand(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        cache = _cache(caching_enabled=True, name=self._NAME)
        fetch, calls = _fetch_returning({"7": "Cached Entry"})

        await cache.get(fetch)
        await cache.get(fetch)

        assert calls[0] == 1
        assert histogram.labels("served") == ["backstop", "cache"]

    @pytest.mark.asyncio
    async def test_waiters_on_one_fetch_are_served_by_coalescing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        cache = _cache(caching_enabled=False, name=self._NAME)
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocked() -> dict[str, str]:
            started.set()
            await release.wait()
            return {"7": "Shared Entry"}

        gets = [asyncio.create_task(cache.get(blocked)) for _ in range(3)]
        await _join_in_flight(started, release)
        await asyncio.wait_for(asyncio.gather(*gets), timeout=5)

        served = histogram.labels("served")
        assert len(served) == 3
        assert served.count("backstop") == 1
        assert served.count("coalesced") == 2

    @pytest.mark.asyncio
    async def test_a_refresh_that_fell_back_to_the_previous_value_is_served_stale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        cache = _cache(caching_enabled=True, name=self._NAME)
        fetch, _calls = _fetch_sequence({"7": "Good Entry"}, ConnectionError("backstop down"))

        await cache.get(fetch)
        _value, freshness = await cache.get(fetch, refresh=True)

        assert freshness == "stale"
        assert histogram.labels("served") == ["backstop", "stale"]

    @pytest.mark.asyncio
    async def test_a_failed_get_is_still_demand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        histogram = self._stub(monkeypatch)
        cache = _cache(caching_enabled=False, name=self._NAME)
        fetch, _calls = _fetch_sequence(ConnectionError("backstop down"))

        with pytest.raises(ConnectionError):
            await cache.get(fetch)

        assert histogram.labels("served") == ["error"]

    @pytest.mark.asyncio
    async def test_a_cancelled_get_is_recorded_as_cancelled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        histogram = self._stub(monkeypatch)
        cache = _cache(caching_enabled=False, name=self._NAME)
        started = asyncio.Event()

        async def never_answers() -> dict[str, str]:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        task = asyncio.create_task(cache.get(never_answers))
        await asyncio.wait_for(started.wait(), timeout=5)
        _ = task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert histogram.labels("served") == ["cancelled"]

    @pytest.mark.asyncio
    async def test_demand_exceeds_fetches_by_exactly_what_the_cache_absorbed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        demand = self._stub(monkeypatch)
        walks = _StubHistogram()
        monkeypatch.setattr("backstop_mcp.caching.cached_value.CATALOG_FETCH_DURATION", walks)
        cache = _cache(caching_enabled=True, name=self._NAME)
        fetch, _calls = _fetch_returning({"7": "Cached Entry"})

        for _ in range(5):
            await cache.get(fetch)

        assert len(demand.records) == 5
        assert len(walks.records) == 1
        assert demand.labels("served").count("cache") == len(demand.records) - len(walks.records)
