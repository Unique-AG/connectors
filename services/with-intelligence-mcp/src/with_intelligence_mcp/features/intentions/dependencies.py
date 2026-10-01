from fastmcp.dependencies import Depends

from with_intelligence_mcp.features.intentions.queries import GetIntentionsQuery
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


def get_intentions_query_factory(
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> GetIntentionsQuery:
    return GetIntentionsQuery(client=client)
