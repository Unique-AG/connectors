from functools import lru_cache

from backstop_mcp.dependencies import get_backstop_config
from backstop_mcp.features.opportunities.opportunity_stages_service import OpportunityStagesService


@lru_cache(maxsize=1)
def get_opportunity_stages_service() -> OpportunityStagesService:
    return OpportunityStagesService.with_ttl_minutes(
        ttl_minutes=get_backstop_config().opportunity_stage_ttl_minutes,
    )
