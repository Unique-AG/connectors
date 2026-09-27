from with_intelligence_mcp.features.investors.resolve_investor_record import (
    InvestorRecordResolution,
    resolve_investor_record,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


class ResolveInvestorRecordQuery:
    def __init__(self, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(self, *, name: str | None, investor_id: int | None) -> InvestorRecordResolution:
        return await resolve_investor_record(self._client, name, investor_id)
