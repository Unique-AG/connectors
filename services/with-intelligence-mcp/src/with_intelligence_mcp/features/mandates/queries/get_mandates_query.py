import asyncio

from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.features.mandates.fetch_mandate import fetch_mandate
from with_intelligence_mcp.features.mandates.fetch_mandates_for_investor import (
    fetch_mandates_for_investor,
)
from with_intelligence_mcp.features.mandates.project_mandate import project_mandate
from with_intelligence_mcp.features.mandates.responses import (
    InvestorMandatesResponse,
    MandateResponse,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


class GetMandatesQuery:
    def __init__(self, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(
        self,
        *,
        investor: InvestorExtendedAttributes,
        limit: int,
        updated_since: str | None,
    ) -> InvestorMandatesResponse:
        listed, total = await fetch_mandates_for_investor(
            self._client,
            investor.id,
            limit=limit,
            updated_since=updated_since,
        )
        details = await asyncio.gather(*(fetch_mandate(self._client, entry.id) for entry in listed))
        mandates = [
            project_mandate(detail) if detail else MandateResponse(id=listed[index].id)
            for index, detail in enumerate(details)
        ]
        return InvestorMandatesResponse(
            investor_id=investor.id,
            investor_name=investor.name,
            mandates=mandates,
            total=total,
            returned=len(mandates),
        )
