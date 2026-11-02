"""`get_report_run_cache`: the production cache keeps 1,000 runs for an hour each."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from datetime import date
from typing import cast

import pytest
from mcp_observability import identifiable_value

from backstop_mcp.features.reports import (
    ReportRun,
    ReportRunCache,
    ReportRunKey,
    RunReportResponse,
    get_report_run_cache,
)

_HOUR = 60 * 60.0


def _key(index: int) -> ReportRunKey:
    return ReportRunKey(
        caller="bob.smith",
        report_name=f"Report {index}",
        as_of_date=date(2026, 8, 31),
        limit=100,
        offset=0,
    )


async def _never_answers() -> RunReportResponse:
    await asyncio.Event().wait()
    raise AssertionError("a parked run is only ever evicted")


class _Runs:
    """Parked runs, cancelled at the end so no task outlives the test."""

    def __init__(self) -> None:
        self.started: list[ReportRun] = []

    def park(self, *, started_at: float | None = None) -> ReportRun:
        run = ReportRun(
            task=asyncio.create_task(_never_answers()),
            started_at=time.monotonic() if started_at is None else started_at,
        )
        self.started.append(run)
        return run


@pytest.fixture
async def runs() -> AsyncGenerator[_Runs]:
    parked = _Runs()
    yield parked
    for run in parked.started:
        run.task.cancel()
    await asyncio.gather(*(run.task for run in parked.started), return_exceptions=True)


class TestEvictionLog:
    @pytest.mark.asyncio
    async def test_an_evicted_run_logs_the_hashed_report_name(
        self, runs: _Runs, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = ReportRunCache(maxsize=1, ttl_seconds=_HOUR)
        cache.add(_key(0), runs.park())

        with caplog.at_level(logging.INFO, logger="backstop_mcp.features.reports.queries"):
            cache.add(_key(1), runs.park())

        [record] = [r for r in caplog.records if r.getMessage() == "Evicted report run"]
        logged = str(cast("object", record.__dict__["report_name"]))
        assert logged == str(identifiable_value("Report 0"))
        assert record.__dict__["reason"] == "full"


class TestProductionDefaults:
    @pytest.mark.asyncio
    async def test_keeps_a_thousand_runs_and_evicts_the_oldest_past_that(self, runs: _Runs) -> None:
        cache: ReportRunCache = get_report_run_cache()
        for index in range(1_000):
            cache.add(_key(index), runs.park())

        assert cache.get(_key(0)) is not None
        cache.add(_key(1_000), runs.park())
        assert cache.get(_key(0)) is None
        assert cache.get(_key(1)) is not None

    @pytest.mark.asyncio
    async def test_keeps_a_run_for_an_hour_from_when_it_started(self, runs: _Runs) -> None:
        cache: ReportRunCache = get_report_run_cache()
        now = time.monotonic()
        cache.add(_key(0), runs.park(started_at=now - _HOUR + 60))
        cache.add(_key(1), runs.park(started_at=now - _HOUR))

        assert cache.get(_key(0)) is not None
        assert cache.get(_key(1)) is None
