from collections.abc import AsyncGenerator

import pytest

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.tasks import GetTasksForPartyQuery
from tests.helpers import client_factory, credential


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_get_tasks_for_party_query(client: BackstopClient) -> GetTasksForPartyQuery:
    return GetTasksForPartyQuery(client=client)
