from collections.abc import AsyncGenerator

import pytest

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields import CustomFieldsService
from backstop_mcp.features.opportunities import (
    GetOpportunitiesByIdsQuery,
    GetOpportunitiesQuery,
    GetStageHistoryQuery,
    MapOpportunityToResponseUtil,
    OpportunityStageResponse,
    OpportunityStagesService,
    SearchOpportunitiesQuery,
)
from tests.helpers import client_factory, credential, custom_fields_service

VOCABULARY: dict[str, OpportunityStageResponse] = {
    stage.id: stage
    for stage in (
        OpportunityStageResponse(id="42478", name="Prospect", closed=False, sort_order=1),
        OpportunityStageResponse(id="42480", name="Project", closed=False, sort_order=2),
        OpportunityStageResponse(id="42482", name="IDD", closed=False, sort_order=3),
        OpportunityStageResponse(id="85446", name="Client Approval", closed=False, sort_order=4),
        OpportunityStageResponse(id="85444", name="Execution", closed=False, sort_order=5),
        OpportunityStageResponse(id="96016", name="Invested", closed=True, sort_order=6),
        OpportunityStageResponse(id="96018", name="Closed", closed=True, sort_order=7),
    )
}


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_map_opportunity_to_response_util(
    client: BackstopClient, *, custom_fields: CustomFieldsService
) -> MapOpportunityToResponseUtil:
    stages = OpportunityStagesService.with_ttl_minutes(client=client, ttl_minutes=60)
    return MapOpportunityToResponseUtil(
        client=client,
        opportunity_stages_service=stages,
        custom_fields_service=custom_fields,
        get_stage_history_query=GetStageHistoryQuery(opportunity_stages_service=stages),
    )


def make_get_opportunities_query(client: BackstopClient) -> GetOpportunitiesQuery:
    custom_fields = custom_fields_service()
    return GetOpportunitiesQuery(
        client=client,
        map_opportunity_to_response_util=make_map_opportunity_to_response_util(
            client, custom_fields=custom_fields
        ),
        custom_fields_service=custom_fields,
    )


def make_get_opportunities_by_ids_query(client: BackstopClient) -> GetOpportunitiesByIdsQuery:
    custom_fields = custom_fields_service()
    return GetOpportunitiesByIdsQuery(
        client=client,
        map_opportunity_to_response_util=make_map_opportunity_to_response_util(
            client, custom_fields=custom_fields
        ),
        custom_fields_service=custom_fields,
    )


def make_search_opportunities_query(client: BackstopClient) -> SearchOpportunitiesQuery:
    custom_fields = custom_fields_service()
    return SearchOpportunitiesQuery(
        client=client,
        map_opportunity_to_response_util=make_map_opportunity_to_response_util(
            client, custom_fields=custom_fields
        ),
        custom_fields_service=custom_fields,
    )
