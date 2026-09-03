from with_intelligence_mcp.features.investments.api_responses import (
    InvestmentListItemAttributes,
)
from with_intelligence_mcp.with_intelligence_client import QueryValue, WithIntelligenceClient

INVESTMENTS_PATH = "/v3/investments"


async def fetch_investments_for_investor(
    client: WithIntelligenceClient,
    investor_id: int,
    *,
    limit: int,
    updated_since: str | None = None,
) -> tuple[list[InvestmentListItemAttributes], int]:
    """Position ids for one investor. The listing carries no detail, so ids are all it gives."""
    params: dict[str, QueryValue] = {"investor_id": [investor_id]}
    if client.settings.asset_class_groups:
        params["asset_class_group"] = list(client.settings.asset_class_groups)
    if updated_since is not None:
        params["updated_at[from]"] = updated_since

    page = await client.get_page(INVESTMENTS_PATH, params, page=1, page_size=limit)
    positions = [
        InvestmentListItemAttributes.model_validate(record)
        for record in page.results
        if "id" in record
    ]
    return positions, page.pagination.total
