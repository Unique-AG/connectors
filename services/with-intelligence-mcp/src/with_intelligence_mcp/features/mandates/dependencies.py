from fastmcp.dependencies import Depends

from with_intelligence_mcp.features.mandates.queries import GetMandatesQuery
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


def get_mandates_query_factory(
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> GetMandatesQuery:
    return GetMandatesQuery(client)
