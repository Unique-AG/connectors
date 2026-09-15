"""Published opportunity-write responses.

A single-deal write reports the stage Backstop landed on after a re-read. A bulk history
backfill reports per-record outcomes — HTTP 201 is not success.
"""

from typing import Literal

from pydantic import Field

from backstop_mcp.models import OmitNoneModel

__all__ = [
    "BackfillOpportunityStageHistoryResponse",
    "RecordOutcomeResponse",
    "UpdatedOpportunityResponse",
]


class UpdatedOpportunityResponse(OmitNoneModel):
    """An opportunity after a PATCH, with the stage Backstop actually stored."""

    id: str = Field(description="Backstop id of the opportunity. Echo it; never invent one.")
    resource_type: str = Field(
        default="opportunities",
        description="Always `opportunities`.",
    )
    stage: str | None = Field(
        default=None,
        description=(
            "Stage name READ BACK after the write. A requested stage that did not move "
            "is named here as the previous stage, with an entry in `warnings`."
        ),
    )
    stage_id: str | None = Field(
        default=None,
        description="Backstop id of that stage, kept even when the name could not be resolved.",
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description=(
            "Silent-failure notes: a requested stage that did not move, or a notify "
            "login that did not match a system user. Empty when the write landed as asked."
        ),
    )


class RecordOutcomeResponse(OmitNoneModel):
    """One row of a multi-record write: applied or failed, never preview."""

    index: int = Field(description="0-based position of this record in the request.")
    record_id: str | None = Field(
        default=None,
        description="Opportunity id this row targeted, when the request supplied one.",
    )
    status: Literal["applied", "failed"] = Field(
        description="Whether Backstop wrote this row. There is no preview status."
    )
    error: str | None = Field(
        default=None,
        description="Backstop's per-record message when `status` is `failed`.",
    )


class BackfillOpportunityStageHistoryResponse(OmitNoneModel):
    """Per-record outcomes of a stage-history backfill. This does not move any deal's stage."""

    total_count: int = Field(description="How many records were sent.")
    applied_count: int = Field(
        description=(
            "How many request rows came back with `status` `applied`. A `201` is not success; "
            "compare this with `total_count`."
        )
    )
    records: tuple[RecordOutcomeResponse, ...] = Field(
        description="One outcome per request record, in request order."
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description=(
            "Messages Backstop returned that could not be attributed to a single request "
            "row. Empty when every message landed on a record."
        ),
    )
