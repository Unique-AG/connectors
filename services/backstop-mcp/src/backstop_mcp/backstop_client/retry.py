"""Tenacity `AsyncRetrying` configuration for Backstop 429 (rate-limit) responses.

`tenacity` supplies the retry mechanics (backoff + jitter, attempt counting); the predicate
and wait strategy here supply the domain decision of what's retryable and how long to wait,
operating directly on `BackstopRateLimitError`.

The split between `RetryPolicy` (built once) and `AsyncRetrying` (built per request) is
deliberate and is explained on `RetryPolicy`.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import tenacity

from backstop_mcp.backstop_client.errors import BackstopRateLimitError
from backstop_mcp.backstop_client.settings import RetrySettings
from backstop_mcp.metrics import BACKSTOP_RATE_LIMITED

logger = logging.getLogger(__name__)

_BACKOFF_INITIAL_SECONDS = 1.0
_BACKOFF_EXP_BASE = 2.0
_BACKOFF_JITTER_SECONDS = 1.0

type RetryPredicate = Callable[[tenacity.RetryCallState], bool]
type WaitStrategy = Callable[[tenacity.RetryCallState], float]


def _record_rate_limit(exc: BackstopRateLimitError, *, retried: bool) -> None:
    """Count one 429, tagged with how it was classified and whether it was retried.

    Recorded here rather than at the raise site in `errors.py` because "whether we retried" is
    only known once the predicate has decided — and the two together are what make the metric
    actionable: a rising `retried=false` with `limit_kind=day` is a quota problem, while
    `retried=true` with `limit_kind=concurrency` is the gate doing its job under load. Both
    labels are bounded, so cardinality is too.
    """
    BACKSTOP_RATE_LIMITED.add(1, {"limit_kind": exc.limit_kind or "unknown", "retried": retried})


def _next_backoff_seconds(attempt_number: int) -> float:
    """Un-jittered exponential backoff for `attempt_number`, used for ceiling checks.

    The predicate needs a deterministic estimate of "what the wait would be" to compare
    against the ceiling; the actual wait (computed by the wait strategy) adds jitter on top.
    """
    return _BACKOFF_INITIAL_SECONDS * (_BACKOFF_EXP_BASE ** (attempt_number - 1))


def _computed_wait_seconds(exc: BackstopRateLimitError, attempt_number: int) -> float:
    # For the no-Retry-After path this is un-jittered, so the ceiling check below is only
    # approximate: the real wait (via `_build_wait_strategy`) adds up to
    # `_BACKOFF_JITTER_SECONDS` more on top, meaning an "approved" wait can sleep up to that
    # much longer than `max_wait_ms`. Accepted tradeoff — see `_next_backoff_seconds`.
    if exc.retry_after_seconds is not None:
        return exc.retry_after_seconds
    return _next_backoff_seconds(attempt_number)


def _build_retry_predicate(settings: RetrySettings) -> RetryPredicate:
    max_wait_seconds = settings.max_wait_ms / 1000

    def predicate(retry_state: tenacity.RetryCallState) -> bool:
        outcome = retry_state.outcome
        if outcome is None or not outcome.failed:
            return False
        exc = outcome.exception()
        if not isinstance(exc, BackstopRateLimitError):
            return False

        # Uncertain classification (limit_kind is None) fails closed, same as a confirmed
        # minute/hour/day quota breach: retrying against the wrong (or unknown) limit wastes
        # attempts and won't resolve.
        if exc.limit_kind != "concurrency":
            logger.info(
                "backstop.rate_limit.quota_exceeded",
                extra={"limit_kind": exc.limit_kind},
            )
            _record_rate_limit(exc, retried=False)
            return False

        wait_seconds = _computed_wait_seconds(exc, retry_state.attempt_number)
        if wait_seconds > max_wait_seconds:
            logger.info(
                "backstop.rate_limit.wait_exceeds_ceiling",
                extra={
                    "wait_seconds": wait_seconds,
                    "max_retry_wait_ms": settings.max_wait_ms,
                },
            )
            _record_rate_limit(exc, retried=False)
            return False

        _record_rate_limit(exc, retried=True)
        return True

    return predicate


def _build_wait_strategy() -> WaitStrategy:
    backoff = tenacity.wait_exponential_jitter(
        initial=_BACKOFF_INITIAL_SECONDS,
        exp_base=_BACKOFF_EXP_BASE,
        jitter=_BACKOFF_JITTER_SECONDS,
    )

    def wait(retry_state: tenacity.RetryCallState) -> float:
        outcome = retry_state.outcome
        exc = outcome.exception() if outcome is not None and outcome.failed else None
        if isinstance(exc, BackstopRateLimitError) and exc.retry_after_seconds is not None:
            return exc.retry_after_seconds
        return backoff(retry_state)

    return wait


def _before_sleep(retry_state: tenacity.RetryCallState) -> None:
    sleep_seconds = retry_state.next_action.sleep if retry_state.next_action is not None else None
    logger.info(
        "backstop.rate_limit.retry",
        extra={
            "attempt_number": retry_state.attempt_number,
            "wait_seconds": sleep_seconds,
        },
    )


@dataclass(frozen=True)
class RetryPolicy:
    """The config-derived half of retrying, built once and shared by every request.

    The decision functions are pure closures over immutable settings, so one set is safe to
    share process-wide — which is the point: `BackstopClient` used to rebuild the predicate, the
    wait strategy and its `wait_exponential_jitter` object on every single call.

    The `AsyncRetrying` wrapper, by contrast, must *not* be shared. Tenacity keeps its per-call
    bookkeeping (`iter_state`, `statistics`) in a `threading.local()`, which is thread-local and
    therefore shared by every coroutine on one event loop. `AsyncRetrying.iter` awaits between
    populating that state and reading it back, so two concurrent requests through a single
    instance would reset each other's `retry_run_result` mid-decision and a retryable 429 could
    be re-raised as final. Hence one cheap wrapper per request, over a policy computed once.
    """

    predicate: RetryPredicate
    wait: WaitStrategy
    max_attempts: int

    def build_retrying(self) -> tenacity.AsyncRetrying:
        """A fresh `AsyncRetrying` for one request. See the class docstring for why per-request."""
        return tenacity.AsyncRetrying(
            retry=self.predicate,
            wait=self.wait,
            stop=tenacity.stop_after_attempt(self.max_attempts),
            before_sleep=_before_sleep,
            # Propagate the original BackstopRateLimitError rather than tenacity's RetryError
            # wrapper, so BackstopClient callers get a clean, typed exception either way
            # (predicate said no, or attempts were exhausted).
            reraise=True,
        )


def build_retry_policy(settings: RetrySettings) -> RetryPolicy:
    """Derive the shareable retry policy from settings. Called once, from the factory."""
    return RetryPolicy(
        predicate=_build_retry_predicate(settings),
        wait=_build_wait_strategy(),
        max_attempts=settings.max_attempts,
    )
