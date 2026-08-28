"""A party's pipeline: what deals they have, what stage each is in, and how it got there.

`fetch_opportunities` is the whole feature — one paginated
`/{segment}/{id}/opportunities?include=stage,stageHistory` walk, projected onto
`OpportunityResponse`/`StageChangeResponse`, then filtered by `status` and ordered by
`dateEnteredCurrentStage` in memory (Backstop rejects the filter and ignores the sort on this
endpoint). See `fetch_opportunities.py`'s module docstring for that and the other measured quirks
it absorbs.

`OpportunityStagesService` is the TTL-cached instance stage vocabulary the fetch is handed: an
opportunity's stage history names only some of the stages it points at, and the rest come from
here. See `opportunity_stages_service.py`.

`fetch_opportunities_by_ids` is the bounded fan-out behind `get_opportunities_by_ids`: one GET
per trusted id, one catalog load for the batch, per-id not-found/error reporting.
"""

from backstop_mcp.features.opportunities.aggregate_search_opportunities import (
    OpportunityGroupBy,
    aggregate_search_opportunities,
)
from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes
from backstop_mcp.features.opportunities.dependencies import get_opportunity_stages_service
from backstop_mcp.features.opportunities.fetch_opportunities import (
    OpportunityStatus,
    fetch_opportunities,
)
from backstop_mcp.features.opportunities.fetch_opportunities_by_ids import (
    MAX_OPPORTUNITY_IDS,
    fetch_opportunities_by_ids,
)
from backstop_mcp.features.opportunities.fetch_search_opportunities import (
    MAX_OPPORTUNITY_SCAN_RECORDS,
    fetch_search_opportunities,
)
from backstop_mcp.features.opportunities.internal_dto import (
    OpportunityStageDto,
    SearchOpportunitiesFetchDto,
    SearchOpportunityDto,
)
from backstop_mcp.features.opportunities.opportunity_stages_service import OpportunityStagesService
from backstop_mcp.features.opportunities.responses import (
    OpportunityFetchResponse,
    OpportunityIdErrorResponse,
    OpportunityResponse,
    StageChangeResponse,
)

__all__ = [
    "MAX_OPPORTUNITY_IDS",
    "MAX_OPPORTUNITY_SCAN_RECORDS",
    "OpportunityFetchResponse",
    "OpportunityGroupBy",
    "OpportunityIdErrorResponse",
    "OpportunityResponse",
    "OpportunityStageDto",
    "OpportunityStageAttributes",
    "OpportunityStagesService",
    "OpportunityStatus",
    "SearchOpportunitiesFetchDto",
    "SearchOpportunityDto",
    "StageChangeResponse",
    "aggregate_search_opportunities",
    "fetch_opportunities",
    "fetch_opportunities_by_ids",
    "fetch_search_opportunities",
    "get_opportunity_stages_service",
]
