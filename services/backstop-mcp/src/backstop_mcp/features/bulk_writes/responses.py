"""Published outcome of one row of a bulk write."""

from typing import Literal

from pydantic import Field

from backstop_mcp.models import OmitNoneModel

__all__ = ["RecordOutcomeResponse"]


class RecordOutcomeResponse(OmitNoneModel):
    """One row of a multi-record write: applied or failed, never preview."""

    index: int = Field(description="0-based position of this record in the request.")
    record_id: str | None = Field(
        default=None,
        description=(
            "Backstop id this row targeted — the definition id for a custom-field write, "
            "the opportunity id for a stage-history row — when the request supplied one."
        ),
    )
    status: Literal["applied", "failed"] = Field(
        description="Whether Backstop wrote this row. There is no preview status."
    )
    error: str | None = Field(
        default=None,
        description="Backstop's per-record message when `status` is `failed`.",
    )
