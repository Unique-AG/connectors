from collections.abc import AsyncGenerator

import pytest

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import (
    GetActivityDetailQuery,
    GetActivityHistoryQuery,
    SearchActivitiesQuery,
)
from backstop_mcp.features.ui_links import BuildEntityLinkUtil
from tests.helpers import client_factory, credential


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_get_activity_detail_query(client: BackstopClient) -> GetActivityDetailQuery:
    return GetActivityDetailQuery(
        client=client, build_entity_link_util=BuildEntityLinkUtil(ui_base_url=None)
    )


def make_get_activity_history_query(
    client: BackstopClient, *, ui_base_url: str | None = None
) -> GetActivityHistoryQuery:
    return GetActivityHistoryQuery(
        client=client, build_entity_link_util=BuildEntityLinkUtil(ui_base_url=ui_base_url)
    )


def make_search_activities_query(client: BackstopClient) -> SearchActivitiesQuery:
    return SearchActivitiesQuery(client=client)
