import logging
from datetime import date
from typing import cast

from opentelemetry import trace

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.reports.api_responses import (
    ReportHeaderAttributes,
    ReportResource,
)
from backstop_mcp.features.reports.responses import ReportColumnResponse, RunReportResponse

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

DEFAULT_REPORT_PAGE_SIZE = 100
MAX_REPORT_PAGE_SIZE = 500


class RunReportQuery:
    """Run one saved Report Center report for a name and as-of date.

    `GET /reports` is not a list of rows. Each HTTP page returns one `reports` resource whose
    `attributes.result.values` holds the rows; `page[limit]`, `page[offset]`, and
    `meta.totalResourceCount` all count those rows. `paginate()` would treat each page as one
    item and stride parallel offsets by 1. This query uses `fetch_page` and flattens
    `result.values`.
    """

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        report_name: str,
        as_of_date: date,
        limit: int,
        offset: int,
    ) -> RunReportResponse:
        assert 1 <= limit <= MAX_REPORT_PAGE_SIZE
        assert offset >= 0
        with _tracer.start_as_current_span("reports.query.run") as span:
            span.set_attribute("report_name", report_name)
            span.set_attribute("as_of_date", as_of_date.isoformat())
            span.set_attribute("limit", limit)
            span.set_attribute("offset", offset)
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
            columns: tuple[ReportColumnResponse, ...] = ()
            rows: list[dict[str, object]] = []
            # Backstop's offset counts the values it sent, not the ones we could read, so
            # paging must advance by `consumed`. Advancing by len(rows) would re-request
            # every dropped value's slot and duplicate rows for the rest of the report.
            consumed = 0
            for report in page.items:
                result = report.attributes.result
                if result is None:
                    continue
                if not columns:
                    columns = self._columns(result.header)
                for value in result.values:
                    consumed += 1
                    row = self._row(value)
                    if row is None:
                        logger.warning("reports.row.unreadable", extra={"report_name": report_name})
                        continue
                    rows.append(row)
            total = page.total_count
            row_count = len(rows)
            next_offset = (
                offset + consumed
                if total is not None and consumed > 0 and offset + consumed < total
                else None
            )
            fetched = RunReportResponse(
                report_name=report_name,
                as_of_date=as_of_date,
                columns=columns,
                rows=tuple(rows),
                row_count=row_count,
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

    def _columns(self, header: list[ReportHeaderAttributes]) -> tuple[ReportColumnResponse, ...]:
        columns: list[ReportColumnResponse] = []
        for column in header:
            name = column.name or column.title
            if name is None:
                continue
            columns.append(ReportColumnResponse(name=name, title=column.title or name))
        return tuple(columns)

    def _row(self, value: object) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        return cast("dict[str, object]", value)
