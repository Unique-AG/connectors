"""Mid-session 401 re-check: probe `/system-info` inside a shared time budget.

A single-shot probe is not enough — `/system-info` itself returned spurious 401s on roughly
half of production login attempts. Sleeps, gate wait, and the probe HTTP timeout all share
this window so a hung probe cannot run to the ordinary CRUD timeout.
"""

import time
from collections.abc import Sequence
from typing import Literal

import httpx

AUTH_RECHECK_INITIAL_DELAY_SECONDS = 1.0
AUTH_RECHECK_BUDGET_SECONDS = 10.0
AUTH_RECHECK_BACKOFF_BASE = 2.0

TRANSIENT_AUTH_MESSAGE = "Backstop temporarily rejected the request. Please retry."

type ProbeOutcome = Literal["ok", "unauthorized", "error"]


class RecheckClock:
    """Counts down the re-check window and the wait before each probe."""

    _budget: float
    _delay: float
    _backoff_base: float
    _started: float

    def __init__(
        self,
        *,
        budget_seconds: float | None = None,
        initial_delay: float | None = None,
        backoff_base: float | None = None,
    ) -> None:
        self._budget = AUTH_RECHECK_BUDGET_SECONDS if budget_seconds is None else budget_seconds
        self._delay = AUTH_RECHECK_INITIAL_DELAY_SECONDS if initial_delay is None else initial_delay
        self._backoff_base = AUTH_RECHECK_BACKOFF_BASE if backoff_base is None else backoff_base
        self._started = time.monotonic()

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)

    def leftover(self) -> float:
        return self._budget - (time.monotonic() - self._started)

    def next_wait(self) -> float | None:
        """Seconds to sleep before the next probe, or `None` if the budget is gone."""
        remaining = self.leftover()
        if remaining <= 0:
            return None
        return min(self._delay, remaining)

    def another_probe_fits(self) -> bool:
        """Grow the next wait. False if that wait would start after the budget."""
        self._delay *= self._backoff_base
        return (time.monotonic() - self._started) + self._delay < self._budget


def probe_outcome(response: httpx.Response) -> ProbeOutcome:
    if response.status_code in {401, 403}:
        return "unauthorized"
    if response.is_error:
        return "error"
    return "ok"


def confirmed_rejection(outcomes: Sequence[ProbeOutcome]) -> bool:
    """Revoke only when every probe that ran came back unauthorized."""
    return bool(outcomes) and all(outcome == "unauthorized" for outcome in outcomes)
