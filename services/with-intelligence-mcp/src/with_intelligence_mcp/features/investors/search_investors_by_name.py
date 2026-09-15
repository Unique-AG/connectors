from pydantic import TypeAdapter

from with_intelligence_mcp.features.investors.fetch_investor import INVESTORS_PATH
from with_intelligence_mcp.features.investors.wi_responses import InvestorListItemAttributes
from with_intelligence_mcp.with_intelligence_client import (
    Page,
    QueryValue,
    WithIntelligenceClient,
)

_INVESTORS_PAGE = TypeAdapter(Page[InvestorListItemAttributes])


async def search_investors_by_name(
    client: WithIntelligenceClient, name: str, *, limit: int = 10
) -> tuple[list[InvestorListItemAttributes], int]:
    """Investors matching `name`, plus how many matched in total.

    Whether With Intelligence's `name` filter is exact or a substring match is not documented; the
    caller handles both by treating one match as resolved and several as ambiguous.
    """
    params: dict[str, QueryValue] = {"name": [name]}
    if client.asset_class_groups:
        params["asset_class_group"] = list(client.asset_class_groups)

    page = await client.get_page(INVESTORS_PATH, _INVESTORS_PAGE, params, page=1, page_size=limit)
    return page.results, page.pagination.total
