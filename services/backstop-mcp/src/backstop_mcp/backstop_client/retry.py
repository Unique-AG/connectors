"""Tenacity `AsyncRetrying` configuration for Backstop 429 (rate-limit) responses.

`tenacity` supplies the retry mechanics (backoff + jitter, attempt counting); the predicate
and wait strategy here supply the domain decision of what's retryable and how long to wait,
operating directly on `BackstopRateLimitError`.
"""

from collections.abc import Callable

import tenacity

from backstop_mcp.backstop_client.errors import BackstopRateLimitError
from backstop_mcp.config import BackstopConfig
from backstop_mcp.logging import get_logger

logger = get_logger(__name__)

_BACKOFF_INITIAL_SECONDS = 1.0
_BACKOFF_EXP_BASE = 2.0
_BACKOFF_JITTER_SECONDS = 1.0


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
    # much longer than `max_retry_wait_ms`. Accepted tradeoff — see `_next_backoff_seconds`.
    if exc.retry_after_seconds is not None:
        return exc.retry_after_seconds
    return _next_backoff_seconds(attempt_number)


def _build_retry_predicate(
    config: BackstopConfig,
) -> Callable[[tenacity.RetryCallState], bool]:
    max_wait_seconds = config.max_retry_wait_ms / 1000

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
            logger.info("backstop.rate_limit.quota_exceeded", limit_kind=exc.limit_kind)
            return False

        wait_seconds = _computed_wait_seconds(exc, retry_state.attempt_number)
        if wait_seconds > max_wait_seconds:
            logger.info(
                "backstop.rate_limit.wait_exceeds_ceiling",
                wait_seconds=wait_seconds,
                max_retry_wait_ms=config.max_retry_wait_ms,
            )
            return False

        return True

    return predicate


def _build_wait_strategy() -> Callable[[tenacity.RetryCallState], float]:
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
        attempt_number=retry_state.attempt_number,
        wait_seconds=sleep_seconds,
    )


def build_retrying(config: BackstopConfig) -> tenacity.AsyncRetrying:
    """Build the `AsyncRetrying` that `BackstopClient._request()` wraps its HTTP call in."""
    return tenacity.AsyncRetrying(
        retry=_build_retry_predicate(config),
        wait=_build_wait_strategy(),
        stop=tenacity.stop_after_attempt(config.max_retry_attempts),
        before_sleep=_before_sleep,
        # Propagate the original BackstopRateLimitError rather than tenacity's RetryError
        # wrapper, so BackstopClient callers get a clean, typed exception either way
        # (predicate said no, or attempts were exhausted).
        reraise=True,
    )
