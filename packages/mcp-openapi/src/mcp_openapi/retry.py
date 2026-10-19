from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import ClassVar, Protocol

import httpx2
import tenacity
from pydantic import BaseModel, ConfigDict, Field

type WaitStrategy = Callable[[tenacity.RetryCallState], float]


class RetryPolicy(Protocol):
    def retrying(self) -> tenacity.AsyncRetrying:
        """A new `AsyncRetrying` for each request.

        Tenacity keeps the state of a call in a thread-local, which every coroutine on the event
        loop shares, so two requests running at once through one instance would corrupt it.
        """
        ...


class RetryAfterPolicy(BaseModel):
    """Retries a status in `statuses` after the delay its `Retry-After` header asks for.

    A response without the header waits for `backoff` instead, capped at `max_wait_seconds`. A
    response that asks for more than `max_wait_seconds` is not retried, because a quota that
    resets in an hour is better reported now than waited out.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    max_attempts: int = Field(default=5, ge=1)
    max_wait_seconds: float = Field(default=30, ge=0)
    backoff: WaitStrategy = Field(
        default_factory=lambda: tenacity.wait_exponential_jitter(initial=1, exp_base=2, jitter=1)
    )
    statuses: frozenset[int] = frozenset({429, 503})

    def retrying(self) -> tenacity.AsyncRetrying:
        return tenacity.AsyncRetrying(
            retry=self._should_retry,
            wait=self._wait,
            stop=tenacity.stop_after_attempt(self.max_attempts),
            reraise=True,
        )

    def _should_retry(self, state: tenacity.RetryCallState) -> bool:
        response = _failed_response(state)
        if response is None or response.status_code not in self.statuses:
            return False
        delay = _retry_after_seconds(response)
        return delay is None or delay <= self.max_wait_seconds

    def _wait(self, state: tenacity.RetryCallState) -> float:
        response = _failed_response(state)
        delay = _retry_after_seconds(response) if response is not None else None
        return min(self.backoff(state), self.max_wait_seconds) if delay is None else delay


DEFAULT_RETRY_POLICY = RetryAfterPolicy()


def _failed_response(state: tenacity.RetryCallState) -> httpx2.Response | None:
    outcome = state.outcome
    error = outcome.exception() if outcome is not None and outcome.failed else None
    return error.response if isinstance(error, httpx2.HTTPStatusError) else None


def _retry_after_seconds(response: httpx2.Response) -> float | None:
    """`Retry-After` as delta-seconds or an HTTP-date (RFC 9110 §10.2.3), None if unreadable."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(UTC)).total_seconds(), 0.0)
