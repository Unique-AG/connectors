from pydantic import TypeAdapter

from with_intelligence_mcp.features.managers.api_responses import ManagerListItemAttributes
from with_intelligence_mcp.with_intelligence_client import Page, QueryValue, WithIntelligenceClient

_MANAGERS_PAGE = TypeAdapter(Page[ManagerListItemAttributes])


async def search_managers_by_name(
    client: WithIntelligenceClient, name: str, *, limit: int = 10
) -> tuple[list[ManagerListItemAttributes], int]:
    """Managers whose name contains `name`, plus how many matched in total."""
    params: dict[str, QueryValue] = {"name": [name]}
    if client.asset_class_groups:
        params["asset_class_group"] = list(client.asset_class_groups)
    page = await client.get_page("/v3/managers", _MANAGERS_PAGE, params, page=1, page_size=limit)
    return page.results, page.pagination.total
