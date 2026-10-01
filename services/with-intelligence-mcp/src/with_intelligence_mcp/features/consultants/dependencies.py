from fastmcp.dependencies import Depends

from with_intelligence_mcp.features.consultants.queries import GetConsultantQuery
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


def get_consultant_query_factory(
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> GetConsultantQuery:
    return GetConsultantQuery(client=client)
