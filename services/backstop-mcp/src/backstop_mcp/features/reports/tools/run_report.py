"""`run_report`: one page of a saved Report Center report, run by name."""

import logging
from datetime import date
from http import HTTPStatus
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from opentelemetry import trace
from pydantic import Field

from backstop_mcp.backstop_client import BackstopApiError
from backstop_mcp.features.reports import (
    DEFAULT_REPORT_PAGE_SIZE,
    MAX_REPORT_PAGE_SIZE,
    RunReportQuery,
    RunReportResponse,
)
from backstop_mcp.features.reports.dependencies import get_run_report_query_factory
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.models import NonEmptyStr, published_output_schema

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

type RunReportToolResponse = RunReportResponse | NotFoundResponse


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(RunReportToolResponse),
)
async def run_report(
    report_name: Annotated[
        NonEmptyStr,
        Field(
            description=(
                "Exact name of a saved report in Report Center. Ask the user for it — there "
                "is no API that lists reports. Never invent or guess a name."
            ),
        ),
    ],
    as_of_date: Annotated[
        date | None,
        Field(
            description=(
                "Date to run the report as of, YYYY-MM-DD. Omit to use today on this server."
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=MAX_REPORT_PAGE_SIZE,
            description=(
                "Rows to return on this page. Defaults to 100. Capped at 500 — Backstop's "
                "recommended report page size. Use `offset` / `next_offset` for more."
            ),
        ),
    ] = DEFAULT_REPORT_PAGE_SIZE,
    offset: Annotated[
        int,
        Field(
            ge=0,
            description=(
                "Row offset to start this page at. Defaults to 0. Echo `next_offset` from a "
                "prior response to continue; do not invent an offset."
            ),
        ),
    ] = 0,
    run_report_query: RunReportQuery = Depends(get_run_report_query_factory),
) -> RunReportToolResponse:
    """Run a saved Report Center report by name and return one page of rows.

    Required: `report_name`, the exact name from Report Center. Ask the user which report —
    there is no list endpoint. Do not invent a name. `as_of_date` defaults to today.

    The result is a table whose columns depend on that saved report. `columns` names the
    keys; `rows` are dicts under those keys. Values can be any type. Ask the user what they
    need from the data and what the columns mean — do not invent a schema or a column's
    meaning.

    One page only. `total` is the full row count; `next_offset` is present when more rows
    remain. Call again with that offset. Do not walk every page unless the user asked for
    the whole report.

    Call like: {"report_name": "<exact Report Center name>"}
    Continue: {"report_name": "<same name>", "as_of_date": "2026-09-17", "offset": 100}
    """
    as_of = as_of_date if as_of_date is not None else date.today()
    with _tracer.start_as_current_span("reports.run") as span:
        span.set_attribute("report_name", report_name)
        span.set_attribute("as_of_date", as_of.isoformat())
        span.set_attribute("limit", limit)
        span.set_attribute("offset", offset)
        logger.info(
            "reports.run.start",
            extra={
                "report_name": report_name,
                "as_of_date": as_of.isoformat(),
                "limit": limit,
                "offset": offset,
            },
        )
        try:
            return await run_report_query.run(
                report_name=report_name,
                as_of_date=as_of,
                limit=limit,
                offset=offset,
            )
        except BackstopApiError as exc:
            if exc.status_code == HTTPStatus.BAD_REQUEST and "not found" in exc.detail.lower():
                return NotFoundResponse(query=report_name, scope="reports")
            raise
