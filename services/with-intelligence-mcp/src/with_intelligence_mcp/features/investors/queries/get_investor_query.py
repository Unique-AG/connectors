from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.features.investors.project_investor import project_investor
from with_intelligence_mcp.features.investors.queries.resolve_investor_record_query import (
    ResolveInvestorRecordQuery,
)
from with_intelligence_mcp.features.investors.responses import (
    InvestorAmbiguousResponse,
    InvestorNotFoundResponse,
    InvestorProfileResponse,
)


class GetInvestorQuery:
    def __init__(self, resolve_investor_record_query: ResolveInvestorRecordQuery) -> None:
        self._resolve_investor_record_query: ResolveInvestorRecordQuery = (
            resolve_investor_record_query
        )

    async def run(
        self, *, name: str | None, investor_id: int | None
    ) -> InvestorProfileResponse | InvestorAmbiguousResponse | InvestorNotFoundResponse:
        record = await self._resolve_investor_record_query.run(name=name, investor_id=investor_id)
        if not isinstance(record, InvestorExtendedAttributes):
            return record
        return project_investor(record)
