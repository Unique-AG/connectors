"""One TTL-cached, single-flight value — the protocol catalogs and stages would otherwise copy.

A `CachedValue` holds one process-wide snapshot. Callers supply the fetch on each `get`, so this
module does not know about Backstop. What it has to get right, once:

- **Double-checked freshness.** A warm read must not queue behind the lock a refresh is holding,
  so the value is checked before taking the lock and again after.
- **In-flight coalescing.** A cold start under load must produce one fetch, not one per caller:
  the owner pins a `Future` that later callers await instead of fetching.
- **A cancelled owner does not cancel its waiters.** Stamping `CancelledError` onto the shared
  future would make every waiter look cancelled itself. They get a `RuntimeError` and may retry.
- **The owner retrieves a stamped failure.** Waiters `await` the shared future; the owner
  re-raises. Calling `.exception()` after `set_exception` marks it retrieved so a cold miss
  with no waiters does not log "Future exception was never retrieved".
- **Unpinning is shielded.** A `CancelledError` arriving during teardown must not skip it, or
  every later `get()` joins a finished future until the process restarts.
- **A failed refresh can serve stale.** When `serve_stale` is on, a value that was right a
  minute ago beats no value, and the TTL is re-stamped so a down Backstop costs one round-trip
  rather than one per call. A *cold* failure has nothing to serve, so it propagates. Stages
  pass `serve_stale=False` so a failed refresh is never softened.

`caching_enabled=False` keeps every mechanism below and consults none of it: the two freshness
checks never hit, nothing is retained, and so the serve-stale branch is unreachable. Request
coalescing is deliberately *not* disabled with it — collapsing concurrent callers onto one
fetch is deduplication, not caching.

**The two histograms that decide a catalog TTL.** They are one view, and the gap between them
is the whole answer:

- `catalog_get_duration_seconds{catalog, served}` — one record per `get`, whatever answered it.
  Its `_count` is demand. `served` says what each caller got — `backstop` (its own fetch),
  `coalesced` (another caller's in-flight fetch), `cache` (a TTL hit), `stale`, `error`,
  `cancelled`.
- `catalog_fetch_duration_seconds{catalog, outcome}` — one record per fetch actually made.

The `catalog` label is `name`. Subtract the `_count`s for requests already avoided.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sized
from datetime import timedelta
from typing import Literal

from backstop_mcp.metrics import CATALOG_FETCH_DURATION, CATALOG_GET_DURATION
from backstop_mcp.timed_gate import TimedGate

__all__ = ["CacheFreshness", "CacheSource", "CachedValue"]

logger = logging.getLogger(__name__)

# Whether the returned value is inside its TTL or is the previous one, re-served because the
# refresh failed. A caller publishes this so a stale answer is never read as a current one.
type CacheFreshness = Literal["ok", "stale"]
# Where a completed load's contents came from, for a holder that meters its loads.
type CacheSource = Literal["backstop", "stale"]
type CacheResult[T] = tuple[T, CacheFreshness]
# Outcome label on `catalog_fetch_duration_seconds`. "cancelled" is its own value rather than
# folded into "error": a cancelled fetch's duration says nothing about how long one takes.
type CacheFetchOutcome = Literal["ok", "error", "cancelled"]
# `served` label on `catalog_get_duration_seconds`: what answered one `get`, one value per call.
type CacheServed = Literal["cache", "coalesced", "backstop", "stale", "error", "cancelled"]


class CachedValue[T]:
    """A TTL'd, single-flight slot holding one `T`.

    `get` is the whole public surface and its shape — `(value, "ok" | "stale")` — is what every
    catalog caller already reads. `snapshot` is applied to every return so a caller cannot
    mutate the stored value.
    """

    def __init__(
        self,
        *,
        ttl: timedelta,
        snapshot: Callable[[T], T],
        name: str,
        log_prefix: str,
        caching_enabled: bool = True,
        serve_stale: bool = True,
        on_load: Callable[[CacheSource], None] | None = None,
    ) -> None:
        self._snapshot: Callable[[T], T] = snapshot
        self._name: str = name
        self._log_prefix: str = log_prefix
        self._caching_enabled: bool = caching_enabled
        self._serve_stale: bool = serve_stale
        self._on_load: Callable[[CacheSource], None] | None = on_load
        self._value: T | None = None
        self._freshness: TimedGate = TimedGate(duration=ttl)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._in_flight: asyncio.Future[CacheResult[T]] | None = None

    async def get(
        self, fetch: Callable[[], Awaitable[T]], *, refresh: bool = False
    ) -> CacheResult[T]:
        """The value, fetching it when cold, past its TTL, or `refresh` was asked for.

        Returns a snapshot, so a caller cannot mutate the stored value. `"stale"` means the
        refresh failed and this is the previous value. With caching disabled every call fetches
        and `"stale"` is never returned. With `serve_stale=False` a failed refresh raises.

        Every call records once into `catalog_get_duration_seconds`, so its `_count` is demand
        rather than fetches — see the module docstring for the pair this forms with the fetch
        histogram.
        """
        started = time.monotonic()
        # Only a `BaseException` that is not an `Exception` can leave this unassigned, and
        # cancellation is the one that happens.
        served: CacheServed = "cancelled"
        try:
            result, served = await self._get_served(fetch, refresh=refresh)
            return result
        except Exception:
            served = "error"
            raise
        finally:
            CATALOG_GET_DURATION.record(
                time.monotonic() - started,
                {"catalog": self._name, "served": served},
            )

    async def _get_served(
        self, fetch: Callable[[], Awaitable[T]], *, refresh: bool
    ) -> tuple[CacheResult[T], CacheServed]:
        """`get`'s actual work, paired with which mechanism answered it."""
        cached = self._servable(refresh=refresh)
        if cached is not None:
            return (self._snapshot(cached), "ok"), "cache"

        async with self._lock:
            cached = self._servable(refresh=refresh)
            if cached is not None:
                return (self._snapshot(cached), "ok"), "cache"
            if self._in_flight is not None and not self._in_flight.done():
                in_flight = self._in_flight
                owner = False
            else:
                in_flight = asyncio.get_running_loop().create_future()
                self._in_flight = in_flight
                owner = True

        if not owner:
            value, status = await in_flight
            # Attributed to the pin, not to the fetch it rode on: this caller made no request,
            # and a stale fetch's own failure is already on the fetch histogram.
            return (self._snapshot(value), status), "coalesced"

        try:
            result = await self._fetch(fetch, in_flight)
            return result, ("stale" if result[1] == "stale" else "backstop")
        except BaseException as error:
            if not in_flight.done():
                # Don't stamp CancelledError onto the shared future — waiters would then
                # look cancelled themselves. A regular exception lets them fail and retry.
                waiter_error: BaseException = error
                if isinstance(error, asyncio.CancelledError):
                    waiter_error = RuntimeError(f"{self._name} fetch was cancelled")
                in_flight.set_exception(waiter_error)
            self._mark_in_flight_exception_retrieved(in_flight)
            raise
        finally:
            # Shield so a CancelledError cannot skip unpinning and leave later
            # get()s joining a finished future until process restart.
            await asyncio.shield(self._unpin_in_flight(in_flight))

    def _servable(self, *, refresh: bool) -> T | None:
        """The held value when it may be served, else `None` — cold, past TTL, or caching off.

        Called on both sides of the lock, which is what makes the freshness check double-checked
        rather than racy.
        """
        if not self._caching_enabled or refresh:
            return None
        cached = self._value
        if cached is None or not self._freshness.within():
            return None
        return cached

    def _mark_in_flight_exception_retrieved(
        self, in_flight: asyncio.Future[CacheResult[T]]
    ) -> None:
        # Waiters still get the exception when they await. This only clears asyncio's
        # "never retrieved" flag for the owner, who re-raises instead of awaiting.
        if in_flight.done() and not in_flight.cancelled():
            _ = in_flight.exception()

    async def _unpin_in_flight(self, in_flight: asyncio.Future[CacheResult[T]]) -> None:
        async with self._lock:
            if self._in_flight is in_flight:
                self._in_flight = None

    async def _metered_fetch(self, fetch: Callable[[], Awaitable[T]]) -> T:
        """The fetch itself, timed into `catalog_fetch_duration_seconds`.

        Recorded in both modes and on every exit — a cancelled fetch is labelled as such rather
        than left unrecorded, so the histogram's `_count` is the true number of fetches started.
        """
        started = time.monotonic()
        outcome: CacheFetchOutcome = "cancelled"
        try:
            value = await fetch()
        except Exception:
            outcome = "error"
            raise
        else:
            outcome = "ok"
            return value
        finally:
            CATALOG_FETCH_DURATION.record(
                time.monotonic() - started,
                {"catalog": self._name, "outcome": outcome},
            )

    def _record_load(self, source: CacheSource) -> None:
        if self._on_load is not None:
            self._on_load(source)

    async def _fetch(
        self, fetch: Callable[[], Awaitable[T]], in_flight: asyncio.Future[CacheResult[T]]
    ) -> CacheResult[T]:
        try:
            value = await self._metered_fetch(fetch)
        except Exception as error:
            held = self._value
            if self._serve_stale and held is not None:
                logger.warning(
                    f"{self._log_prefix}.refresh_failed_serving_stale",
                    extra={
                        "catalog": self._name,
                        "fetched_at": (
                            self._freshness.marked_at.isoformat()
                            if self._freshness.marked_at
                            else None
                        ),
                    },
                    exc_info=True,
                )
                self._record_load("stale")
                self._freshness.mark()
                result: CacheResult[T] = (self._snapshot(held), "stale")
                in_flight.set_result(result)
                return result
            in_flight.set_exception(error)
            raise

        if self._caching_enabled:
            # Nothing is retained with caching off, which is also what makes the serve-stale
            # branch above unreachable in that mode rather than needing its own guard.
            self._value = value
            self._freshness.mark()
        self._record_load("backstop")
        extra: dict[str, object] = {"catalog": self._name}
        count = _item_count(value)
        if count is not None:
            extra["items"] = count
        logger.info(f"{self._log_prefix}.refreshed", extra=extra)
        result = (self._snapshot(value), "ok")
        in_flight.set_result(result)
        return result


def _item_count(value: object) -> int | None:
    if isinstance(value, Sized) and not isinstance(value, (str, bytes, bytearray)):
        return len(value)
    return None
