from pydantic import TypeAdapter

from with_intelligence_mcp.features.mandates.wi_responses import MandateListItemAttributes
from with_intelligence_mcp.with_intelligence_client import Page, QueryValue, WithIntelligenceClient

MANDATES_PATH = "/v3/mandates"
_MANDATES_PAGE = TypeAdapter(Page[MandateListItemAttributes])


async def fetch_mandates_for_investor(
    client: WithIntelligenceClient,
    investor_id: int,
    *,
    limit: int,
    updated_since: str | None = None,
) -> tuple[list[MandateListItemAttributes], int]:
    """Mandate ids for one investor. Detail lives behind `GET /{id}`, as everywhere else."""
    params: dict[str, QueryValue] = {"investor_id": [investor_id], "sort[updated_at]": "desc"}
    if client.asset_class_groups:
        params["asset_class_group"] = list(client.asset_class_groups)
    if updated_since is not None:
        params["updated_at[from]"] = updated_since

    page = await client.get_page(MANDATES_PATH, _MANDATES_PAGE, params, page=1, page_size=limit)
    return page.results, page.pagination.total
