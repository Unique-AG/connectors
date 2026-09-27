from functools import lru_cache

from fastmcp.dependencies import Depends

from with_intelligence_mcp.features.persons.queries import GetPeopleForInvestorQuery
from with_intelligence_mcp.features.persons.resource_utils import MapPersonToResponseUtil
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


@lru_cache(maxsize=1)
def get_map_person_to_response_util_factory() -> MapPersonToResponseUtil:
    return MapPersonToResponseUtil()


def get_people_for_investor_query_factory(
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
    map_person_to_response_util: MapPersonToResponseUtil = Depends(
        get_map_person_to_response_util_factory
    ),
) -> GetPeopleForInvestorQuery:
    return GetPeopleForInvestorQuery(
        client=client,
        map_person_to_response_util=map_person_to_response_util,
    )
