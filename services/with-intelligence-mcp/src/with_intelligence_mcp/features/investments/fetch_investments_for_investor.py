from pydantic import TypeAdapter

from with_intelligence_mcp.features.investments.wi_responses import (
    InvestmentListItemAttributes,
)
from with_intelligence_mcp.with_intelligence_client import Page, QueryValue, WithIntelligenceClient

INVESTMENTS_PATH = "/v3/investments"
_INVESTMENTS_PAGE = TypeAdapter(Page[InvestmentListItemAttributes])


async def fetch_investments_for_investor(
    client: WithIntelligenceClient,
    investor_id: int,
    *,
    limit: int,
    updated_since: str | None = None,
) -> tuple[list[InvestmentListItemAttributes], int]:
    """Position ids for one investor. The listing carries no detail, so ids are all it gives."""
    params: dict[str, QueryValue] = {"investor_id": [investor_id]}
    if client.asset_class_groups:
        params["asset_class_group"] = list(client.asset_class_groups)
    if updated_since is not None:
        params["updated_at[from]"] = updated_since

    page = await client.get_page(
        INVESTMENTS_PATH, _INVESTMENTS_PAGE, params, page=1, page_size=limit
    )
    return page.results, page.pagination.total
