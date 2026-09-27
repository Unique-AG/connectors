from functools import lru_cache

from fastmcp.dependencies import Depends

from with_intelligence_mcp.features.investors.queries import (
    GetInvestorQuery,
    ResolveInvestorRecordQuery,
)
from with_intelligence_mcp.features.investors.resource_utils import MapInvestorToResponseUtil
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


def get_resolve_investor_record_query_factory(
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> ResolveInvestorRecordQuery:
    return ResolveInvestorRecordQuery(client)


@lru_cache(maxsize=1)
def get_map_investor_to_response_util_factory() -> MapInvestorToResponseUtil:
    return MapInvestorToResponseUtil()


def get_investor_query_factory(
    resolve_investor_record_query: ResolveInvestorRecordQuery = Depends(
        get_resolve_investor_record_query_factory
    ),
    map_investor_to_response_util: MapInvestorToResponseUtil = Depends(
        get_map_investor_to_response_util_factory
    ),
) -> GetInvestorQuery:
    return GetInvestorQuery(
        resolve_investor_record_query=resolve_investor_record_query,
        map_investor_to_response_util=map_investor_to_response_util,
    )
