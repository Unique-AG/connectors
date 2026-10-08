import asyncio
import logging
import time
from datetime import date
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from backstop_mcp.features.reports.responses import RunReportResponse

logger = logging.getLogger(__name__)

# How long a run is kept for a later call to collect, in flight or finished. A failed run is
# dropped as soon as it fails (`RunReportQuery`).
REPORT_RUN_TTL_SECONDS = 60 * 60.0
# Most runs kept at once; past it the oldest is evicted.
REPORT_RUN_CACHE_SIZE = 1_000


class ReportRunKey(BaseModel):
    """One caller's request for one page of one report as of one date."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    caller: str
    report_name: str
    as_of_date: date
    limit: int
    offset: int


class ReportRun(BaseModel):
    """One `GET /reports` page in flight, or finished and not yet collected."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    task: asyncio.Task[RunReportResponse]
    started_at: float


class ReportRunCache:
    """Runs by key: at most `maxsize`, each kept `ttl_seconds` from when it started.

    Evicting a run — expired, or the oldest when full — cancels its request if it is still in
    flight, so a run nobody comes back for does not hold a Backstop connection forever. Runs
    are inserted as they start, so dict order is age order and the first entries are the
    oldest.
    """

    def __init__(self, *, maxsize: int, ttl_seconds: float) -> None:
        assert maxsize >= 1
        self._maxsize: int = maxsize
        self._ttl_seconds: float = ttl_seconds
        self._runs: dict[ReportRunKey, ReportRun] = {}

    def get(self, key: ReportRunKey) -> ReportRun | None:
        self._expire()
        return self._runs.get(key)

    def add(self, key: ReportRunKey, run: ReportRun) -> None:
        assert key not in self._runs
        self._expire()
        while len(self._runs) >= self._maxsize:
            self._evict(next(iter(self._runs)), reason="full")
        self._runs[key] = run

    def discard(self, key: ReportRunKey, run: ReportRun) -> None:
        """Drop `run` once collected; a newer run under the same key stays."""
        if self._runs.get(key) is run:
            del self._runs[key]

    def _expire(self) -> None:
        deadline = time.monotonic() - self._ttl_seconds
        expired = [key for key, run in self._runs.items() if run.started_at <= deadline]
        for key in expired:
            self._evict(key, reason="expired")

    def _evict(self, key: ReportRunKey, *, reason: str) -> None:
        run = self._runs.pop(key)
        if not run.task.done():
            run.task.cancel()
            logger.info(
                "reports.run.evicted",
                extra={"report_name": key.report_name, "reason": reason},
            )
