from fastmcp.dependencies import Depends

from with_intelligence_mcp.features.persons.queries import GetPeopleForInvestorQuery
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


def get_people_for_investor_query_factory(
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> GetPeopleForInvestorQuery:
    return GetPeopleForInvestorQuery(client=client)
