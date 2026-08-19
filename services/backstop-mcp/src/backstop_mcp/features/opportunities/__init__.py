"""A party's pipeline: what deals they have, what stage each is in, and how it got there.

`fetch_opportunities` is the whole feature — one paginated
`/{segment}/{id}/opportunities?include=stage,stageHistory` walk, projected onto
`OpportunityResponse`/`StageChangeResponse`, then filtered by `status` and ordered by
`dateEnteredCurrentStage` in memory (Backstop rejects the filter and ignores the sort on this
endpoint). See `fetch.py`'s module docstring for that and the other measured quirks it absorbs.

`OpportunityStagesService` is the TTL-cached instance stage vocabulary the fetch is handed: an
opportunity's stage history names only some of the stages it points at, and the rest come from
here. See `stages.py`.
"""

from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes
from backstop_mcp.features.opportunities.fetch import (
    OpportunityStatus,
    fetch_opportunities,
)
from backstop_mcp.features.opportunities.internal_dto import OpportunityStageDto
from backstop_mcp.features.opportunities.responses import (
    OpportunityFetchResponse,
    OpportunityResponse,
    StageChangeResponse,
)
from backstop_mcp.features.opportunities.stages import (
    OpportunityStagesService,
    create_opportunity_stages_service,
)

__all__ = [
    "OpportunityFetchResponse",
    "OpportunityResponse",
    "OpportunityStageDto",
    "OpportunityStageAttributes",
    "OpportunityStagesService",
    "OpportunityStatus",
    "StageChangeResponse",
    "create_opportunity_stages_service",
    "fetch_opportunities",
]
