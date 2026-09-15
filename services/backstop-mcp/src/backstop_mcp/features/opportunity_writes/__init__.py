"""Write-back for opportunities: create or PATCH one deal, or append stage-history rows."""

from backstop_mcp.features.opportunity_writes.backfill_opportunity_stage_history_input import (
    BACKFILL_OPPORTUNITY_STAGE_HISTORY_INPUT_DESCRIPTION,
    MAX_STAGE_HISTORY_RECORDS,
    BackfillOpportunityStageHistoryInput,
    OpportunityStageHistoryRecordInput,
)
from backstop_mcp.features.opportunity_writes.commands import (
    BackfillOpportunityStageHistoryCommand,
    CreateOpportunityCommand,
    UpdateOpportunityCommand,
)
from backstop_mcp.features.opportunity_writes.create_opportunity_input import (
    CREATE_OPPORTUNITY_INPUT_DESCRIPTION,
    CreateOpportunityInput,
)
from backstop_mcp.features.opportunity_writes.dependencies import (
    get_backfill_opportunity_stage_history_command_factory,
    get_create_opportunity_command_factory,
    get_update_opportunity_command_factory,
)
from backstop_mcp.features.opportunity_writes.responses import (
    BackfillOpportunityStageHistoryResponse,
    CreatedOpportunityResponse,
    CreateOpportunityResponse,
    RecordOutcomeResponse,
    UpdatedOpportunityResponse,
)
from backstop_mcp.features.opportunity_writes.update_opportunity_input import (
    UPDATE_OPPORTUNITY_INPUT_DESCRIPTION,
    UpdateOpportunityInput,
)

__all__ = [
    "BACKFILL_OPPORTUNITY_STAGE_HISTORY_INPUT_DESCRIPTION",
    "CREATE_OPPORTUNITY_INPUT_DESCRIPTION",
    "MAX_STAGE_HISTORY_RECORDS",
    "UPDATE_OPPORTUNITY_INPUT_DESCRIPTION",
    "BackfillOpportunityStageHistoryCommand",
    "BackfillOpportunityStageHistoryInput",
    "BackfillOpportunityStageHistoryResponse",
    "CreateOpportunityCommand",
    "CreateOpportunityInput",
    "CreateOpportunityResponse",
    "CreatedOpportunityResponse",
    "OpportunityStageHistoryRecordInput",
    "RecordOutcomeResponse",
    "UpdateOpportunityCommand",
    "UpdateOpportunityInput",
    "UpdatedOpportunityResponse",
    "get_backfill_opportunity_stage_history_command_factory",
    "get_create_opportunity_command_factory",
    "get_update_opportunity_command_factory",
]
