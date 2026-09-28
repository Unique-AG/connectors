import asyncio
import logging

from pydantic import TypeAdapter

from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.features.mandates.api_responses import (
    MandateExtendedAttributes,
    MandateListItemAttributes,
)
from with_intelligence_mcp.features.mandates.responses import (
    InvestorMandatesResponse,
    MandateResponse,
)
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
    NotFound,
    Page,
    QueryValue,
    WithIntelligenceClient,
)

logger = logging.getLogger(__name__)
_MANDATE_RESPONSE = TypeAdapter(MandateExtendedAttributes)
_MANDATES_PAGE = TypeAdapter(Page[MandateListItemAttributes])


class GetMandatesQuery:
    def __init__(self, *, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(
        self,
        *,
        investor: InvestorExtendedAttributes,
        page: int,
        limit: int,
        updated_since: str | None,
    ) -> InvestorMandatesResponse:
        listed, total = await _fetch_mandates_for_investor(
            self._client,
            investor.id,
            page=page,
            limit=limit,
            updated_since=updated_since,
        )
        details = await asyncio.gather(
            *(_fetch_mandate(self._client, entry.id) for entry in listed)
        )
        mandates = [
            MandateResponse.from_attributes(detail)
            if detail
            else MandateResponse(id=listed[index].id)
            for index, detail in enumerate(details)
        ]
        response = InvestorMandatesResponse(
            investor_id=investor.id,
            investor_name=investor.name,
            mandates=mandates,
            total=total,
            returned=len(mandates),
            page=page,
            has_more=(page - 1) * limit + len(mandates) < total,
        )
        logger.info(
            "mandates.investor.fetched",
            extra={"investor_id": investor.id, "returned": response.returned, "total": total},
        )
        return response


async def _fetch_mandate(
    client: WithIntelligenceClient, mandate_id: int
) -> MandateExtendedAttributes | None:
    try:
        return await client.get_json(f"/v3/mandates/{mandate_id}", _MANDATE_RESPONSE)
    except NotEntitled, NotFound:
        return None


async def _fetch_mandates_for_investor(
    client: WithIntelligenceClient,
    investor_id: int,
    *,
    page: int,
    limit: int,
    updated_since: str | None,
) -> tuple[list[MandateListItemAttributes], int]:
    params: dict[str, QueryValue] = {
        "investor_id": [investor_id],
        "sort[updated_at]": "desc",
    }
    if client.asset_class_groups:
        params["asset_class_group"] = list(client.asset_class_groups)
    if updated_since is not None:
        params["updated_at[from]"] = updated_since

    response = await client.get_page(
        "/v3/mandates", _MANDATES_PAGE, params, page=page, page_size=limit
    )
    return response.results, response.pagination.total
