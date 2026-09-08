from collections.abc import AsyncGenerator

import pytest

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import (
    GetActivityDetailQuery,
    GetActivityHistoryQuery,
    SearchActivitiesQuery,
)
from tests.helpers import client_factory, credential


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_get_activity_detail_query(client: BackstopClient) -> GetActivityDetailQuery:
    return GetActivityDetailQuery(client=client)


def make_get_activity_history_query(client: BackstopClient) -> GetActivityHistoryQuery:
    return GetActivityHistoryQuery(client=client)


def make_search_activities_query(client: BackstopClient) -> SearchActivitiesQuery:
    return SearchActivitiesQuery(client=client)
