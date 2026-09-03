"""A party's pipeline: what deals they have, what stage each is in, and how it got there."""

from backstop_mcp.features.opportunities.api_responses import (
    OpportunityResourceAttributes,
    OpportunityStageAttributes,
)
from backstop_mcp.features.opportunities.dependencies import (
    get_opportunities_by_ids_query_factory,
    get_opportunities_query_factory,
    get_opportunity_stages_service_factory,
    get_search_opportunities_query_factory,
    get_stage_history_query_factory,
)
from backstop_mcp.features.opportunities.opportunity_stages_service import OpportunityStagesService
from backstop_mcp.features.opportunities.queries import (
    MAX_OPPORTUNITY_IDS,
    MAX_OPPORTUNITY_SCAN_RECORDS,
    GetOpportunitiesByIdsQuery,
    GetOpportunitiesQuery,
    OpportunityGroupBy,
    OpportunityStatus,
    SearchMode,
    SearchOpportunitiesQuery,
)
from backstop_mcp.features.opportunities.resource_utils import (
    GetStageHistoryQuery,
    MapOpportunityToResponseUtil,
    aggregate_search_opportunities,
)
from backstop_mcp.features.opportunities.responses import (
    GetOpportunitiesByIdsResponse,
    OpportunitiesResolvedResponse,
    OpportunityIdErrorResponse,
    OpportunityResponse,
    OpportunityStageResponse,
    PartyOpportunitiesResponse,
    SearchOpportunitiesResolvedResponse,
    StageChangeResponse,
)

__all__ = [
    "MAX_OPPORTUNITY_IDS",
    "MAX_OPPORTUNITY_SCAN_RECORDS",
    "GetOpportunitiesByIdsQuery",
    "GetOpportunitiesByIdsResponse",
    "GetOpportunitiesQuery",
    "GetStageHistoryQuery",
    "MapOpportunityToResponseUtil",
    "OpportunitiesResolvedResponse",
    "OpportunityGroupBy",
    "OpportunityIdErrorResponse",
    "OpportunityResponse",
    "OpportunityResourceAttributes",
    "OpportunityStageAttributes",
    "OpportunityStageResponse",
    "OpportunityStagesService",
    "OpportunityStatus",
    "PartyOpportunitiesResponse",
    "SearchMode",
    "SearchOpportunitiesQuery",
    "SearchOpportunitiesResolvedResponse",
    "StageChangeResponse",
    "aggregate_search_opportunities",
    "get_opportunities_by_ids_query_factory",
    "get_opportunities_query_factory",
    "get_opportunity_stages_service_factory",
    "get_search_opportunities_query_factory",
    "get_stage_history_query_factory",
]
