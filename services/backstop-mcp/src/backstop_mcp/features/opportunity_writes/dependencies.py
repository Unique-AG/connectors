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
    DeleteOpportunityCommand,
    UpdateOpportunityCommand,
)
from backstop_mcp.features.system_users import SystemUsersService, get_system_users_service
from backstop_mcp.features.ui_links import (
    BuildEntityLinkUtil,
    get_build_entity_link_util_factory,
)


@lru_cache(maxsize=1)
def get_update_opportunity_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    opportunity_stages_service: OpportunityStagesService = Depends(
        get_opportunity_stages_service_factory
    ),
    system_users_service: SystemUsersService = Depends(get_system_users_service),
    build_entity_link_util: BuildEntityLinkUtil = Depends(get_build_entity_link_util_factory),
) -> UpdateOpportunityCommand:
    return UpdateOpportunityCommand(
        client=client,
        opportunity_stages_service=opportunity_stages_service,
        system_users_service=system_users_service,
        build_entity_link_util=build_entity_link_util,
    )


@lru_cache(maxsize=1)
def get_create_opportunity_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    opportunity_stages_service: OpportunityStagesService = Depends(
        get_opportunity_stages_service_factory
    ),
    system_users_service: SystemUsersService = Depends(get_system_users_service),
    build_entity_link_util: BuildEntityLinkUtil = Depends(get_build_entity_link_util_factory),
) -> CreateOpportunityCommand:
    return CreateOpportunityCommand(
        client=client,
        opportunity_stages_service=opportunity_stages_service,
        system_users_service=system_users_service,
        build_entity_link_util=build_entity_link_util,
    )


@lru_cache(maxsize=1)
def get_delete_opportunity_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> DeleteOpportunityCommand:
    return DeleteOpportunityCommand(client=client)


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
