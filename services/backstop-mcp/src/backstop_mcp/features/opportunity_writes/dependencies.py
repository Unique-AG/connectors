from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.opportunities import (
    OpportunityStagesService,
    get_opportunity_stages_service_factory,
)
from backstop_mcp.features.opportunity_writes.commands import (
    BackfillOpportunityStageHistoryCommand,
    CreateOpportunityCommand,
    UpdateOpportunityCommand,
)
from backstop_mcp.features.system_users import SystemUsersService, get_system_users_service


@lru_cache(maxsize=1)
def get_update_opportunity_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    opportunity_stages_service: OpportunityStagesService = Depends(
        get_opportunity_stages_service_factory
    ),
    system_users_service: SystemUsersService = Depends(get_system_users_service),
) -> UpdateOpportunityCommand:
    return UpdateOpportunityCommand(
        client=client,
        opportunity_stages_service=opportunity_stages_service,
        system_users_service=system_users_service,
    )


@lru_cache(maxsize=1)
def get_create_opportunity_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    opportunity_stages_service: OpportunityStagesService = Depends(
        get_opportunity_stages_service_factory
    ),
    system_users_service: SystemUsersService = Depends(get_system_users_service),
) -> CreateOpportunityCommand:
    return CreateOpportunityCommand(
        client=client,
        opportunity_stages_service=opportunity_stages_service,
        system_users_service=system_users_service,
    )


@lru_cache(maxsize=1)
def get_backfill_opportunity_stage_history_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    opportunity_stages_service: OpportunityStagesService = Depends(
        get_opportunity_stages_service_factory
    ),
) -> BackfillOpportunityStageHistoryCommand:
    return BackfillOpportunityStageHistoryCommand(
        client=client,
        opportunity_stages_service=opportunity_stages_service,
    )
