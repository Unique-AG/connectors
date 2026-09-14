"""`backfill_opportunity_stage_history`: append history rows. Does not move a deal's stage."""

import logging
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.opportunity_writes import (
    BACKFILL_OPPORTUNITY_STAGE_HISTORY_INPUT_DESCRIPTION,
    BackfillOpportunityStageHistoryCommand,
    BackfillOpportunityStageHistoryInput,
    BackfillOpportunityStageHistoryResponse,
    get_backfill_opportunity_stage_history_command_factory,
)
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(BackfillOpportunityStageHistoryResponse),
)
async def backfill_opportunity_stage_history(
    backfill: Annotated[
        BackfillOpportunityStageHistoryInput,
        Field(description=BACKFILL_OPPORTUNITY_STAGE_HISTORY_INPUT_DESCRIPTION),
    ],
    backfill_opportunity_stage_history_command: BackfillOpportunityStageHistoryCommand = Depends(
        get_backfill_opportunity_stage_history_command_factory
    ),
) -> BackfillOpportunityStageHistoryResponse:
    """Append historical stage-history rows. This does not move any deal's current stage.

    Each row needs an opportunity id, a stage **name** from this instance's vocabulary, and
    an effective date. A validation failure on any name blocks the whole batch — nothing is
    written. A `201` is not success: read `records[].status`. As a side effect Backstop
    rewrites `previousStage` on the affected deals to the backfilled stage, even though
    `relationships.stage` does not change. To move a deal, call `update_opportunity` once
    per deal.

    Call like: {"backfill": {"records": [{"opportunity_id": "<id from get_opportunities>",
    "stage": "IDD", "effective_date": "2026-02-01"}]}}
    """
    logger.info(
        "opportunity_writes.backfill_stage_history.start",
        extra={"record_count": len(backfill.records)},
    )
    return await backfill_opportunity_stage_history_command.run(backfill=backfill)
