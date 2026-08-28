"""One TTL-cached, single-flight catalog — the protocol four features would otherwise each copy.

A catalog here is a small, instance-wide `{id: dto}` map that many tool calls read and nothing
writes: activity tags, system users, custom-field definitions, custom-field groups. Each is one
paginated walk, too expensive to repeat per tool call and too cheap and too derived to persist,
so each is held in memory behind a TTL.

Getting them there is the subtlest concurrency in the service, and it was copy-pasted four times
— identical but for identifier names, with the comments explaining *why* surviving in only one
copy. What it has to get right, once:

- **Double-checked freshness.** A warm read must not queue behind the lock a refresh is holding,
  so the cache is checked before taking the lock and again after.
- **In-flight coalescing.** A cold start under load must produce one walk, not one per caller:
  the owner pins a `Future` that later callers await instead of fetching.
- **A cancelled owner does not cancel its waiters.** Stamping `CancelledError` onto the shared
  future would make every waiter look cancelled itself. They get a `RuntimeError` and may retry.
- **The owner retrieves a stamped failure.** Waiters `await` the shared future; the owner
  re-raises. Calling `.exception()` after `set_exception` marks it retrieved so a cold miss
  with no waiters does not log "Future exception was never retrieved".
- **Unpinning is shielded.** A `CancelledError` arriving during teardown must not skip it, or
  every later `get()` joins a finished future until the process restarts.
- **A failed refresh serves stale.** A catalog that was right a minute ago beats no catalog, and
  the TTL is re-stamped so a down Backstop costs one round-trip rather than one per call. A
  *cold* failure has nothing to serve, so it propagates.

Subclasses supply the DTO, the fetch, and the names this logs under. `get` is the whole public
surface and its shape — `(catalog, "ok" | "stale")` — is what every caller already reads.

**Caching is per feature, from the environment.** Each provider in a feature's
`dependencies.py` passes `caching_enabled` from a `BACKSTOP_*_CACHE_ENABLED` flag. The
custom-field catalogs default on (3,274 definitions, 2.77 MiB, 6.15 s measured); activity tags
and system users still default off. Nothing here is deleted for a flag that is off: the TTL,
the double-check, the in-flight pin and the serve-stale path all still work, and flipping one
catalog is one env var.

**The two histograms that decide it.** They are one view, and the gap between them is the whole
answer:

- `catalog_get_duration_seconds{catalog, served}` — one record per `get`, whatever answered it.
  Its `_count` is demand: the number of walks there would be with no cache and no coalescing,
  which is the counterfactual the caching decision needs. `served` says what each caller got —
  `backstop` (its own walk), `coalesced` (another caller's in-flight walk), `cache` (a TTL hit),
  `stale`, `error`, `cancelled` — and its duration is caller-visible latency, lock and
  coalescing wait included.
- `catalog_fetch_duration_seconds{catalog, outcome}` — one record per walk actually made,
  however many callers were served from it. Its buckets are the walk cost.

Subtract the `_count`s for requests already avoided, and read `served` for which mechanism
avoided them. With caching off, any gap is coalescing alone; the `served="cache"` rate a TTL
would add is what the histograms are there to predict, and then to confirm once one is on.

What the disabled mode changes: the two freshness checks never hit, no items are retained, and
so the serve-stale branch is unreachable — a failure propagates instead of being softened by a
catalog this mode never kept. Request coalescing is deliberately *not* disabled with it:
collapsing concurrent callers onto one walk is deduplication, not caching, and turning it off
would multiply exactly the load this is trying to measure.

`OpportunityStagesService` deliberately does *not* use this; see its own docstring for why a
seven-row vocabulary wants a failure to propagate rather than be softened.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Literal

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.metrics import CATALOG_FETCH_DURATION, CATALOG_GET_DURATION
from backstop_mcp.timed_gate import TimedGate

__all__ = ["CachedCatalog", "CatalogFreshness", "CatalogSource"]

logger = logging.getLogger(__name__)

# Whether the returned catalog is inside its TTL or is the previous one, re-served because the
# refresh failed. A caller publishes this so a stale answer is never read as a current one.
type CatalogFreshness = Literal["ok", "stale"]
# Where a completed load's contents came from, for a catalog that meters its loads.
type CatalogSource = Literal["backstop", "stale"]
type CatalogResult[T] = tuple[dict[str, T], CatalogFreshness]
# Outcome label on `catalog_fetch_duration_seconds`. "cancelled" is its own value rather than
# folded into "error": a cancelled walk's duration says nothing about how long one takes.
type CatalogFetchOutcome = Literal["ok", "error", "cancelled"]
# `served` label on `catalog_get_duration_seconds`: what answered one `get`, one value per call.
# The three that are not a walk of this caller's own are the ones a caching decision reads —
# `cache` is what a TTL bought, `coalesced` what the in-flight pin bought without one.
type CatalogServed = Literal["cache", "coalesced", "backstop", "stale", "error", "cancelled"]


class CachedCatalog[T]:
    """A TTL'd, single-flight, serve-stale catalog of `T` keyed by Backstop id.

    Subclassed rather than composed so each feature keeps its own class name, its own docstring
    and its own `with_ttl_minutes`, and so `get`'s return type narrows to that feature's DTO.

    `caching_enabled=False` keeps every mechanism below and consults none of it — see the module
    docstring for which catalogs currently pass that.
    """

    def __init__(
        self,
        *,
        ttl: timedelta,
        fetch: Callable[[BackstopClient], Awaitable[dict[str, T]]],
        log_prefix: str,
        subject: str,
        caching_enabled: bool = True,
    ) -> None:
        self._fetch_items: Callable[[BackstopClient], Awaitable[dict[str, T]]] = fetch
        self._log_prefix: str = log_prefix
        self._subject: str = subject
        self._caching_enabled: bool = caching_enabled
        self._items: dict[str, T] | None = None
        self._freshness: TimedGate = TimedGate(duration=ttl)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._in_flight: asyncio.Future[CatalogResult[T]] | None = None

    async def get(self, client: BackstopClient, *, refresh: bool = False) -> CatalogResult[T]:
        """The catalog, fetching it when cold, past its TTL, or `refresh` was asked for.

        Returns a copy, so a caller cannot mutate the shared map. `"stale"` means the refresh
        failed and this is the previous catalog. With caching disabled every call fetches and
        `"stale"` is never returned.

        Every call records once into `catalog_get_duration_seconds`, so its `_count` is demand
        rather than walks — see the module docstring for the pair this forms with the walk
        histogram.
        """
        started = time.monotonic()
        # Only a `BaseException` that is not an `Exception` can leave this unassigned, and
        # cancellation is the one that happens.
        served: CatalogServed = "cancelled"
        try:
            result, served = await self._get_served(client, refresh=refresh)
            return result
        except Exception:
            served = "error"
            raise
        finally:
            CATALOG_GET_DURATION.record(
                time.monotonic() - started,
                {"catalog": self._subject, "served": served},
            )

    async def _get_served(
        self, client: BackstopClient, *, refresh: bool
    ) -> tuple[CatalogResult[T], CatalogServed]:
        """`get`'s actual work, paired with which mechanism answered it."""
        cached = self._servable(refresh=refresh)
        if cached is not None:
            return (dict(cached), "ok"), "cache"

        async with self._lock:
            cached = self._servable(refresh=refresh)
            if cached is not None:
                return (dict(cached), "ok"), "cache"
            if self._in_flight is not None and not self._in_flight.done():
                in_flight = self._in_flight
                owner = False
            else:
                in_flight = asyncio.get_running_loop().create_future()
                self._in_flight = in_flight
                owner = True

        if not owner:
            items, status = await in_flight
            # Attributed to the pin, not to the walk it rode on: this caller made no request,
            # and a stale walk's own failure is already on the fetch histogram.
            return (dict(items), status), "coalesced"

        try:
            result = await self._fetch(client, in_flight)
            return result, ("stale" if result[1] == "stale" else "backstop")
        except BaseException as error:
            if not in_flight.done():
                # Don't stamp CancelledError onto the shared future — waiters would then
                # look cancelled themselves. A regular exception lets them fail and retry.
                waiter_error: BaseException = error
                if isinstance(error, asyncio.CancelledError):
                    waiter_error = RuntimeError(f"{self._subject} catalog fetch was cancelled")
                in_flight.set_exception(waiter_error)
            self._mark_in_flight_exception_retrieved(in_flight)
            raise
        finally:
            # Shield so a CancelledError cannot skip unpinning and leave later
            # get()s joining a finished future until process restart.
            await asyncio.shield(self._unpin_in_flight(in_flight))

    def record_load(self, source: CatalogSource) -> None:
        """Called once per completed load. Override in a catalog that meters them."""
        _ = source

    def _servable(self, *, refresh: bool) -> dict[str, T] | None:
        """The held catalog when it may be served, else `None` — cold, past TTL, or caching off.

        Called on both sides of the lock, which is what makes the freshness check double-checked
        rather than racy.
        """
        if not self._caching_enabled or refresh:
            return None
        cached = self._items
        if cached is None or not self._freshness.within():
            return None
        return cached

    def _mark_in_flight_exception_retrieved(
        self, in_flight: asyncio.Future[CatalogResult[T]]
    ) -> None:
        # Waiters still get the exception when they await. This only clears asyncio's
        # "never retrieved" flag for the owner, who re-raises instead of awaiting.
        if in_flight.done() and not in_flight.cancelled():
            _ = in_flight.exception()

    async def _unpin_in_flight(self, in_flight: asyncio.Future[CatalogResult[T]]) -> None:
        async with self._lock:
            if self._in_flight is in_flight:
                self._in_flight = None

    async def _metered_fetch(self, client: BackstopClient) -> dict[str, T]:
        """The walk itself, timed into `catalog_fetch_duration_seconds`.

        Recorded in both modes and on every exit — a cancelled walk is labelled as such rather
        than left unrecorded, so the histogram's `_count` is the true number of walks started.
        """
        started = time.monotonic()
        outcome: CatalogFetchOutcome = "cancelled"
        try:
            items = await self._fetch_items(client)
        except Exception:
            outcome = "error"
            raise
        else:
            outcome = "ok"
            return items
        finally:
            CATALOG_FETCH_DURATION.record(
                time.monotonic() - started,
                {"catalog": self._subject, "outcome": outcome},
            )

    async def _fetch(
        self, client: BackstopClient, in_flight: asyncio.Future[CatalogResult[T]]
    ) -> CatalogResult[T]:
        try:
            items = await self._metered_fetch(client)
        except Exception as error:
            if self._items is not None:
                logger.warning(
                    f"{self._log_prefix}.refresh_failed_serving_stale",
                    extra={
                        "catalog": self._subject,
                        "fetched_at": (
                            self._freshness.marked_at.isoformat()
                            if self._freshness.marked_at
                            else None
                        ),
                    },
                    exc_info=True,
                )
                self.record_load("stale")
                self._freshness.mark()
                result: CatalogResult[T] = (dict(self._items), "stale")
                in_flight.set_result(result)
                return result
            in_flight.set_exception(error)
            raise

        if self._caching_enabled:
            # Nothing is retained with caching off, which is also what makes the serve-stale
            # branch above unreachable in that mode rather than needing its own guard.
            self._items = items
            self._freshness.mark()
        self.record_load("backstop")
        logger.info(
            f"{self._log_prefix}.refreshed",
            extra={"catalog": self._subject, "items": len(items)},
        )
        result = (dict(items), "ok")
        in_flight.set_result(result)
        return result
