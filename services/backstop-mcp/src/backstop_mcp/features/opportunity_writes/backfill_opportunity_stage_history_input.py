"""Input for appending historical stage-history rows. This does not move any deal's stage."""

from datetime import date

from pydantic import BaseModel, Field

from backstop_mcp.models import NonEmptyStr

__all__ = [
    "BACKFILL_OPPORTUNITY_STAGE_HISTORY_INPUT_DESCRIPTION",
    "MAX_STAGE_HISTORY_RECORDS",
    "BackfillOpportunityStageHistoryInput",
    "OpportunityStageHistoryRecordInput",
]

MAX_STAGE_HISTORY_RECORDS = 15

BACKFILL_OPPORTUNITY_STAGE_HISTORY_INPUT_DESCRIPTION = (
    "Required. Historical stage-history rows to append. This does not move any deal's "
    "current stage — use `update_opportunity` for that. At most "
    f"{MAX_STAGE_HISTORY_RECORDS} records. Each row needs an opportunity id, a stage "
    "name, and an effective date."
)


class OpportunityStageHistoryRecordInput(BaseModel):
    """One historical stage-history row. A row with no date is meaningless."""

    opportunity_id: NonEmptyStr = Field(
        description="Backstop opportunity id. Never invent or guess."
    )
    stage: NonEmptyStr = Field(
        description="Stage **name** from this instance's vocabulary, not an id."
    )
    effective_date: date = Field(
        description="Day this historical stage row should be dated. Required."
    )


class BackfillOpportunityStageHistoryInput(BaseModel):
    """A batch of historical stage-history rows. Does not move any deal's stage."""

    records: tuple[OpportunityStageHistoryRecordInput, ...] = Field(
        min_length=1,
        max_length=MAX_STAGE_HISTORY_RECORDS,
        description=(
            f"Historical rows to append, 1 to {MAX_STAGE_HISTORY_RECORDS}. This endpoint "
            "does not move a deal's current stage; it rewrites `previousStage` as a side "
            "effect. To move a deal, call `update_opportunity` once per deal."
        ),
    )
