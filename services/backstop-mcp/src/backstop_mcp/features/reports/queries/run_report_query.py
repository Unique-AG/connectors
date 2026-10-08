import asyncio
import logging
import time
from datetime import date
from typing import cast

from opentelemetry import trace

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.reports.api_responses import ReportHeaderAttributes, ReportResource
from backstop_mcp.features.reports.queries.report_run_cache import (
    ReportRun,
    ReportRunCache,
    ReportRunKey,
)
from backstop_mcp.features.reports.responses import RunReportPendingResponse, RunReportResponse

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

DEFAULT_REPORT_PAGE_SIZE = 100
MAX_REPORT_PAGE_SIZE = 500

# Below the agent's tool-call timeout, so a cold build answers "still running" instead of
# the call being cut off.
REPORT_WAIT_SECONDS = 50.0


def _retrieve_exception(task: asyncio.Task[RunReportResponse]) -> None:
    # A run that fails after every caller gave up would otherwise log "Task exception was
    # never retrieved"; the client already logged the failure itself.
    if not task.cancelled():
        task.exception()


class RunReportQuery:
    """Run one saved Report Center report for a name and as-of date.

    `GET /reports` is not a list of rows. Each HTTP page returns one `reports` resource whose
    `attributes.result.values` holds the rows; `page[limit]`, `page[offset]`, and
    `meta.totalResourceCount` all count those rows. `paginate()` would treat each page as one
    item and stride parallel offsets by 1. This query uses `fetch_page` and flattens
    `result.values`.

    A cold report can take Backstop minutes to build; once built, Backstop serves it in
    seconds. So every call goes through a run that waits at most `wait_seconds`; a run that
    outlives that is cached per caller, report, as-of date, and page (see `ReportRunCache`).
    A later call for the same page collects it rather than sending another request. The query
    and its cache are process singletons, so the runs are per replica.
    """

    def __init__(
        self,
        *,
        client: BackstopClient,
        run_cache: ReportRunCache,
        wait_seconds: float = REPORT_WAIT_SECONDS,
    ) -> None:
        self._client: BackstopClient = client
        self._runs: ReportRunCache = run_cache
        self._wait_seconds: float = wait_seconds

    async def run(
        self,
        *,
        report_name: str,
        as_of_date: date,
        limit: int,
        offset: int,
    ) -> RunReportResponse | RunReportPendingResponse:
        assert 1 <= limit <= MAX_REPORT_PAGE_SIZE
        assert offset >= 0
        with _tracer.start_as_current_span("reports.query.run") as span:
            span.set_attribute("report_name", report_name)
            span.set_attribute("as_of_date", as_of_date.isoformat())
            span.set_attribute("limit", limit)
            span.set_attribute("offset", offset)
            key = ReportRunKey(
                caller=await self._client.caller_username(),
                report_name=report_name,
                as_of_date=as_of_date,
                limit=limit,
                offset=offset,
            )
            run = self._runs.get(key)
            span.set_attribute("joined", run is not None)
            if run is None:
                run = self._start_run(key)
                self._runs.add(key, run)
            # `asyncio.wait` neither cancels the run on timeout nor when this call is cancelled.
            done, _ = await asyncio.wait({run.task}, timeout=self._wait_seconds)
            if not done:
                running_seconds = round(time.monotonic() - run.started_at)
                span.set_attribute("pending", True)
                logger.info(
                    "reports.run.pending",
                    extra={
                        "report_name": report_name,
                        "as_of_date": as_of_date.isoformat(),
                        "running_seconds": running_seconds,
                    },
                )
                return RunReportPendingResponse(
                    report_name=report_name,
                    as_of_date=as_of_date,
                    limit=limit,
                    offset=offset,
                    running_seconds=running_seconds,
                )
            self._runs.discard(key, run)
            return run.task.result()

    def _start_run(self, key: ReportRunKey) -> ReportRun:
        task = asyncio.create_task(
            self._fetch(
                report_name=key.report_name,
                as_of_date=key.as_of_date,
                limit=key.limit,
                offset=key.offset,
            )
        )
        task.add_done_callback(_retrieve_exception)
        return ReportRun(task=task, started_at=time.monotonic())

    async def _fetch(
        self,
        *,
        report_name: str,
        as_of_date: date,
        limit: int,
        offset: int,
    ) -> RunReportResponse:
        with _tracer.start_as_current_span("reports.query.fetch"):
            page = await self._client.fetch_page(
                "/reports",
                schema=ReportResource,
                params={
                    "filter[reportName][eq]": report_name,
                    "filter[asOfDate][eq]": as_of_date.isoformat(),
                },
                page_size=limit,
                offset=offset,
            )
            header: list[ReportHeaderAttributes] = []
            records: list[dict[str, object]] = []
            # Backstop's offset counts values it sent, not rows we could read; advancing by
            # len(records) would re-request each dropped slot and duplicate the rest.
            consumed = 0
            for report in page.items:
                result = report.attributes.result
                if result is None:
                    continue
                if not header:
                    header = result.header
                for value in result.values:
                    consumed += 1
                    if not isinstance(value, dict):
                        logger.warning("reports.row.unreadable", extra={"report_name": report_name})
                        continue
                    records.append(cast("dict[str, object]", value))
            columns = self._columns(header, records)
            rows = tuple(tuple(record.get(key) for key in columns) for record in records)
            total = page.total_count
            next_offset = (
                offset + consumed
                if total is not None and consumed > 0 and offset + consumed < total
                else None
            )
            fetched = RunReportResponse(
                report_name=report_name,
                as_of_date=as_of_date,
                columns=tuple(columns.values()),
                rows=rows,
                row_count=len(rows),
                total=total,
                offset=offset,
                next_offset=next_offset,
            )
            logger.info(
                "reports.fetched",
                extra={
                    "report_name": report_name,
                    "as_of_date": as_of_date.isoformat(),
                    "offset": offset,
                    "limit": limit,
                    "row_count": fetched.row_count,
                    "total": fetched.total,
                },
            )
            return fetched

    def _columns(
        self, header: list[ReportHeaderAttributes], records: list[dict[str, object]]
    ) -> dict[str, str]:
        """Row key -> published title, in report order."""
        columns: dict[str, str] = {}
        for column in header:
            key = column.name or column.title
            if key is not None:
                columns.setdefault(key, column.title or key)
        # A cell under a key the header did not list would otherwise vanish from the table.
        for record in records:
            for key in record:
                columns.setdefault(key, key)
        return columns
