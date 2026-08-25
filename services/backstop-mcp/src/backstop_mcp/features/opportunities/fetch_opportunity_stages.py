from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes
from backstop_mcp.features.opportunities.internal_dto import OpportunityStageDto

_STAGES_PATH = "/opportunity-stages"
_STAGES_PAGE_SIZE = 100


async def fetch_opportunity_stages(client: BackstopClient) -> dict[str, OpportunityStageDto]:
    """Fetch the instance's opportunity-stage vocabulary, keyed by stage id."""
    page = await client.paginate(
        _STAGES_PATH,
        schema=BackstopApiResource[OpportunityStageAttributes],
        max_records=None,
        page_size=_STAGES_PAGE_SIZE,
    )

    stages: dict[str, OpportunityStageDto] = {}
    for resource in page.items:
        stage = OpportunityStageDto.from_resource(resource)
        if stage is not None:
            stages[stage.id] = stage
    return stages
