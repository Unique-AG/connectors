from fastmcp.dependencies import Depends

from with_intelligence_mcp.features.investors.queries import (
    GetInvestorQuery,
    ResolveInvestorRecordQuery,
)
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


def get_resolve_investor_record_query_factory(
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> ResolveInvestorRecordQuery:
    return ResolveInvestorRecordQuery(client)


def get_investor_query_factory(
    resolve_investor_record_query: ResolveInvestorRecordQuery = Depends(
        get_resolve_investor_record_query_factory
    ),
) -> GetInvestorQuery:
    return GetInvestorQuery(resolve_investor_record_query)
