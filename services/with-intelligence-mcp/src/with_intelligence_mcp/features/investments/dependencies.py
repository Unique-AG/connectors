from functools import lru_cache

from fastmcp.dependencies import Depends

from with_intelligence_mcp.features.investments.queries import GetInvestmentsQuery
from with_intelligence_mcp.features.investments.resource_utils import MapPositionToResponseUtil
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


@lru_cache(maxsize=1)
def get_map_position_to_response_util_factory() -> MapPositionToResponseUtil:
    return MapPositionToResponseUtil()


def get_investments_query_factory(
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
    map_position_to_response_util: MapPositionToResponseUtil = Depends(
        get_map_position_to_response_util_factory
    ),
) -> GetInvestmentsQuery:
    return GetInvestmentsQuery(
        client=client,
        map_position_to_response_util=map_position_to_response_util,
    )
