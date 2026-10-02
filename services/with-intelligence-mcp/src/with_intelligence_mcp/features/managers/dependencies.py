from fastmcp.dependencies import Depends

from with_intelligence_mcp.features.managers.queries import GetManagerQuery
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


def get_manager_query_factory(
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> GetManagerQuery:
    return GetManagerQuery(client=client)
