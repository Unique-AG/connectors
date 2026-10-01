from pydantic import TypeAdapter

from with_intelligence_mcp.features.consultants.api_responses import ConsultantListItemAttributes
from with_intelligence_mcp.with_intelligence_client import Page, QueryValue, WithIntelligenceClient

_CONSULTANTS_PAGE = TypeAdapter(Page[ConsultantListItemAttributes])


async def search_consultants_by_name(
    client: WithIntelligenceClient, name: str, *, limit: int = 10
) -> tuple[list[ConsultantListItemAttributes], int]:
    """Consultants whose name contains `name`, plus how many matched in total."""
    params: dict[str, QueryValue] = {"name": [name]}
    if client.asset_class_groups:
        params["asset_class_group"] = list(client.asset_class_groups)
    page = await client.get_page(
        "/v3/consultants", _CONSULTANTS_PAGE, params, page=1, page_size=limit
    )
    return page.results, page.pagination.total
