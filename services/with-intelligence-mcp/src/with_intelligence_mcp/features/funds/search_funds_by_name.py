from pydantic import TypeAdapter

from with_intelligence_mcp.features.funds.api_responses import FundListItemAttributes
from with_intelligence_mcp.with_intelligence_client import (
    Page,
    QueryValue,
    WithIntelligenceClient,
)

_FUNDS_PAGE = TypeAdapter(Page[FundListItemAttributes])


async def search_funds_by_name(
    client: WithIntelligenceClient, name: str, *, limit: int = 10
) -> tuple[list[FundListItemAttributes], int]:
    """Funds whose name contains `name`, plus how many matched in total."""
    params: dict[str, QueryValue] = {"name": [name]}
    if client.asset_class_groups:
        params["asset_class_group"] = list(client.asset_class_groups)
    page = await client.get_page("/v3/funds", _FUNDS_PAGE, params, page=1, page_size=limit)
    return page.results, page.pagination.total
