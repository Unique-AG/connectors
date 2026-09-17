"""Published shape of one page of a named Report Center report."""

from datetime import date
from typing import ClassVar

from pydantic import ConfigDict, Field

from backstop_mcp.models import OmitNoneModel

__all__ = ["ReportColumnResponse", "RunReportResponse"]


class ReportColumnResponse(OmitNoneModel):
    """One column on this report's result table.

    Names and titles come from the saved report. They are not a stable vocabulary — a Report
    Builder edit can rename or replace a column.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str = Field(
        description=(
            "Column key used on each row. Echo it when talking about a cell; do not invent "
            "column names."
        )
    )
    title: str = Field(
        description="Column title as the report published it. Often the same as `name`."
    )


class RunReportResponse(OmitNoneModel):
    """One page of rows from a saved Report Center report, run as of a date.

    Column meanings are report-specific. Ask the user what they need from the data — this
    envelope cannot describe a report's cells.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    report_name: str = Field(
        description="Exact Report Center name that was run. Echo it; do not invent a name."
    )
    as_of_date: date = Field(
        description="As-of date sent to Backstop, as YYYY-MM-DD. Today when the caller omitted it."
    )
    columns: tuple[ReportColumnResponse, ...] = Field(
        description=(
            "Columns on this page, in report order. Keys on `rows` match `name`. Empty when "
            "the page has no header."
        )
    )
    rows: tuple[dict[str, object], ...] = Field(
        description=(
            "Result rows on this page. Keys are this report's column names; values can be any "
            "type. Ask the user what the columns mean — do not invent a schema."
        )
    )
    row_count: int = Field(description="How many rows are on this page.")
    total: int | None = Field(
        default=None,
        description=(
            "Total rows Backstop reports for this run (`meta.totalResourceCount`). Omitted "
            "when the envelope has no count."
        ),
    )
    offset: int = Field(description="Row offset requested for this page.")
    next_offset: int | None = Field(
        default=None,
        description=(
            "Pass as `offset` to fetch the next page. Omitted when this page is the last, or "
            "when the total is unknown."
        ),
    )
