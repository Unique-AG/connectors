"""A party's pipeline: what deals they have, what stage each is in, and how it got there.

`GetOpportunitiesQuery` walks `/{segment}/{id}/opportunities?include=stage,stageHistory`,
projects onto `OpportunityResponse`/`StageChangeResponse`, then filters by `status` and orders
by `dateEnteredCurrentStage` in memory (Backstop rejects the filter and ignores the sort on this
endpoint).

`GetOpportunitiesByIdsQuery` is the bounded fan-out behind `get_opportunities_by_ids`: one GET
per trusted id, per-id not-found/error reporting.

`SearchOpportunitiesQuery` is the firm-wide `GET /opportunities` walk behind `search_opportunities`.
"""

from backstop_mcp.features.opportunities.aggregate_search_opportunities import (
    OpportunityGroupBy,
    aggregate_search_opportunities,
)
from backstop_mcp.features.opportunities.api_responses import (
    OpportunityResourceAttributes,
    OpportunityStageAttributes,
)
from backstop_mcp.features.opportunities.dependencies import get_opportunity_stages_service_factory
from backstop_mcp.features.opportunities.opportunity_stages_service import OpportunityStagesService
from backstop_mcp.features.opportunities.queries import (
    MAX_OPPORTUNITY_IDS,
    MAX_OPPORTUNITY_SCAN_RECORDS,
    GetOpportunitiesByIdsQuery,
    GetOpportunitiesQuery,
    OpportunityStatus,
    SearchMode,
    SearchOpportunitiesQuery,
)
from backstop_mcp.features.opportunities.responses import (
    GetOpportunitiesByIdsResponse,
    GetOpportunitiesResponse,
    OpportunityIdErrorResponse,
    OpportunityResponse,
    OpportunityStageResponse,
    SearchOpportunitiesResolvedResponse,
    StageChangeResponse,
)

__all__ = [
    "MAX_OPPORTUNITY_IDS",
    "MAX_OPPORTUNITY_SCAN_RECORDS",
    "GetOpportunitiesByIdsQuery",
    "GetOpportunitiesByIdsResponse",
    "GetOpportunitiesQuery",
    "GetOpportunitiesResponse",
    "OpportunityGroupBy",
    "OpportunityIdErrorResponse",
    "OpportunityResponse",
    "OpportunityResourceAttributes",
    "OpportunityStageAttributes",
    "OpportunityStageResponse",
    "OpportunityStagesService",
    "OpportunityStatus",
    "SearchMode",
    "SearchOpportunitiesQuery",
    "SearchOpportunitiesResolvedResponse",
    "StageChangeResponse",
    "aggregate_search_opportunities",
    "get_opportunity_stages_service_factory",
]
