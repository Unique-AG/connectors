"""Published shapes of a named Report Center report run: one page, or still running."""

from datetime import date
from typing import ClassVar, Literal

from pydantic import ConfigDict, Field

from backstop_mcp.models import OmitNoneModel

__all__ = ["RunReportPendingResponse", "RunReportResponse"]


class RunReportResponse(OmitNoneModel):
    """One page of a saved Report Center report, run as of a date, as a table.

    `rows` is the data the user asked for. Answer from the cells; a list of the columns is not
    an answer.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    report_name: str = Field(
        description="Exact Report Center name that was run. Echo it; do not invent a name."
    )
    as_of_date: date = Field(
        description="As-of date sent to Backstop, as YYYY-MM-DD. Today when the caller omitted it."
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
            "Pass as `offset` to fetch the next page, copied exactly; never compute or guess an "
            "offset. Omitted when this page is the last, or when the total is unknown."
        ),
    )
    columns: tuple[str, ...] = Field(
        description=(
            "Table header: column titles in report order, as the saved report publishes them. "
            "A Report Builder edit can rename them, so read them on every run."
        )
    )
    rows: tuple[tuple[object, ...], ...] = Field(
        description=(
            "Table body: one list per row, cell i under `columns[i]`. Null is an empty cell. "
            "Values keep Backstop's types (text, number, boolean)."
        )
    )


class RunReportPendingResponse(OmitNoneModel):
    """Backstop is still building this report; no rows yet.

    A cold report can take minutes to build. The run keeps going on the server, so a later call
    with the same `report_name`, `as_of_date`, `limit`, and `offset` picks it up instead of
    starting over.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: Literal["running"] = Field(
        default="running", description="Always `running`: the report has no rows yet."
    )
    report_name: str = Field(description="Exact Report Center name that is being run.")
    as_of_date: date = Field(
        description="As-of date the run uses, as YYYY-MM-DD. Repeat it on the next call."
    )
    limit: int = Field(description="Page size the run uses. Repeat it on the next call.")
    offset: int = Field(description="Row offset the run uses. Repeat it on the next call.")
    running_seconds: int = Field(
        description=(
            "How long Backstop has been building this report. Call run_report again now with "
            "the same `report_name`, `as_of_date`, `limit`, and `offset`; each call already "
            "waits on the server, so don't pause first. If it is still running after a few "
            "calls, tell the user how long it has been building and offer to check again "
            "later. Never invent rows while it runs."
        )
    )
