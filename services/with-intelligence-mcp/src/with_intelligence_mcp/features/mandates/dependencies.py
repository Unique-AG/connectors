from functools import lru_cache

from fastmcp.dependencies import Depends

from with_intelligence_mcp.features.mandates.queries import GetMandatesQuery
from with_intelligence_mcp.features.mandates.resource_utils import MapMandateToResponseUtil
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


@lru_cache(maxsize=1)
def get_map_mandate_to_response_util_factory() -> MapMandateToResponseUtil:
    return MapMandateToResponseUtil()


def get_mandates_query_factory(
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
    map_mandate_to_response_util: MapMandateToResponseUtil = Depends(
        get_map_mandate_to_response_util_factory
    ),
) -> GetMandatesQuery:
    return GetMandatesQuery(
        client=client,
        map_mandate_to_response_util=map_mandate_to_response_util,
    )
