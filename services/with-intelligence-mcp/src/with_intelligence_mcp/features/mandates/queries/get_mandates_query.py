import asyncio
import logging

from pydantic import TypeAdapter

from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.features.mandates.api_responses import MandateExtendedAttributes
from with_intelligence_mcp.features.mandates.fetch_mandates_for_investor import (
    MANDATES_PATH,
    fetch_mandates_for_investor,
)
from with_intelligence_mcp.features.mandates.responses import (
    InvestorMandatesResponse,
    MandateResponse,
)
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
    NotFound,
    WithIntelligenceClient,
)

logger = logging.getLogger(__name__)
_MANDATE_RESPONSE = TypeAdapter(MandateExtendedAttributes)


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
        listed, total = await fetch_mandates_for_investor(
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
        return await client.get_json(f"{MANDATES_PATH}/{mandate_id}", _MANDATE_RESPONSE)
    except NotEntitled, NotFound:
        return None
