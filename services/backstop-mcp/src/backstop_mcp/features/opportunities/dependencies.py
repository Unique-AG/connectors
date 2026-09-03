from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.config import BackstopConfig
from backstop_mcp.dependencies import get_backstop_client_for_current_caller, get_backstop_config
from backstop_mcp.features.custom_fields import CustomFieldsService, get_custom_fields_service
from backstop_mcp.features.opportunities.opportunity_stages_service import OpportunityStagesService
from backstop_mcp.features.opportunities.queries import (
    GetOpportunitiesByIdsQuery,
    GetOpportunitiesQuery,
    SearchOpportunitiesQuery,
)
from backstop_mcp.features.opportunities.resource_utils import (
    GetStageHistoryQuery,
    MapOpportunityToResponseUtil,
)


@lru_cache(maxsize=1)
def get_opportunity_stages_service_factory(
    settings: BackstopConfig = Depends(get_backstop_config),
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> OpportunityStagesService:
    return OpportunityStagesService.with_ttl_minutes(
        ttl_minutes=settings.opportunity_stage_ttl_minutes, client=client
    )


@lru_cache(maxsize=1)
def get_stage_history_query_factory(
    opportunity_stages_service: OpportunityStagesService = Depends(
        get_opportunity_stages_service_factory
    ),
) -> GetStageHistoryQuery:
    return GetStageHistoryQuery(opportunity_stages_service=opportunity_stages_service)


def get_map_opportunity_to_response_util_factory(
    opportunity_stages_service: OpportunityStagesService = Depends(
        get_opportunity_stages_service_factory
    ),
    get_stage_history_query: GetStageHistoryQuery = Depends(get_stage_history_query_factory),
    custom_fields_service: CustomFieldsService = Depends(get_custom_fields_service),
) -> MapOpportunityToResponseUtil:
    return MapOpportunityToResponseUtil(
        opportunity_stages_service=opportunity_stages_service,
        custom_fields_service=custom_fields_service,
        get_stage_history_query=get_stage_history_query,
    )


@lru_cache(maxsize=1)
def get_opportunities_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    map_opportunity_to_response_util: MapOpportunityToResponseUtil = Depends(
        get_map_opportunity_to_response_util_factory
    ),
    custom_fields_service: CustomFieldsService = Depends(get_custom_fields_service),
) -> GetOpportunitiesQuery:
    return GetOpportunitiesQuery(
        client=client,
        map_opportunity_to_response_util=map_opportunity_to_response_util,
        custom_fields_service=custom_fields_service,
    )


@lru_cache(maxsize=1)
def get_opportunities_by_ids_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    map_opportunity_to_response_util: MapOpportunityToResponseUtil = Depends(
        get_map_opportunity_to_response_util_factory
    ),
    custom_fields_service: CustomFieldsService = Depends(get_custom_fields_service),
) -> GetOpportunitiesByIdsQuery:
    return GetOpportunitiesByIdsQuery(
        client=client,
        map_opportunity_to_response_util=map_opportunity_to_response_util,
        custom_fields_service=custom_fields_service,
    )


@lru_cache(maxsize=1)
def get_search_opportunities_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    map_opportunity_to_response_util: MapOpportunityToResponseUtil = Depends(
        get_map_opportunity_to_response_util_factory
    ),
    custom_fields_service: CustomFieldsService = Depends(get_custom_fields_service),
) -> SearchOpportunitiesQuery:
    return SearchOpportunitiesQuery(
        client=client,
        map_opportunity_to_response_util=map_opportunity_to_response_util,
        custom_fields_service=custom_fields_service,
    )
