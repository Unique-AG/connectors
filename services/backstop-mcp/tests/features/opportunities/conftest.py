from collections.abc import AsyncGenerator

import pytest

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunities.internal_dto import OpportunityStageDto
from backstop_mcp.features.opportunities.oppportunity_stage_service_v2 import (
    OpportunityStagesServiceV2,
)
from backstop_mcp.features.opportunities.queries.get_opportunities_by_ids_query import (
    GetOpportunitiesByIdsQuery,
)
from backstop_mcp.features.opportunities.queries.get_opportunities_query import (
    GetOpportunitiesQuery,
)
from backstop_mcp.features.opportunities.resource_utils import GetStageHistoryQuery
from backstop_mcp.features.opportunities.resource_utils.map_opportunity_to_response_util import (
    MapOpportunityToResponseUtil,
)
from tests.helpers import client_factory, credential, custom_fields_service

VOCABULARY: dict[str, OpportunityStageDto] = {
    stage.id: stage
    for stage in (
        OpportunityStageDto(id="42478", name="Prospect", closed=False, sort_order=1),
        OpportunityStageDto(id="42480", name="Project", closed=False, sort_order=2),
        OpportunityStageDto(id="42482", name="IDD", closed=False, sort_order=3),
        OpportunityStageDto(id="85446", name="Client Approval", closed=False, sort_order=4),
        OpportunityStageDto(id="85444", name="Execution", closed=False, sort_order=5),
        OpportunityStageDto(id="96016", name="Invested", closed=True, sort_order=6),
        OpportunityStageDto(id="96018", name="Closed", closed=True, sort_order=7),
    )
}


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_map_opportunity_to_response_util(client: BackstopClient) -> MapOpportunityToResponseUtil:
    stages = OpportunityStagesServiceV2.with_ttl_minutes(client=client, ttl_minutes=60)
    return MapOpportunityToResponseUtil(
        client=client,
        opportunity_stages_service=stages,
        custom_fields_service=custom_fields_service(),
        get_stage_history_query=GetStageHistoryQuery(opportunity_stages_service=stages),
    )


def make_get_opportunities_query(client: BackstopClient) -> GetOpportunitiesQuery:
    return GetOpportunitiesQuery(
        client=client,
        map_opportunity_to_response_util=make_map_opportunity_to_response_util(client),
    )


def make_get_opportunities_by_ids_query(client: BackstopClient) -> GetOpportunitiesByIdsQuery:
    return GetOpportunitiesByIdsQuery(
        client=client,
        map_opportunity_to_response_util=make_map_opportunity_to_response_util(client),
    )
