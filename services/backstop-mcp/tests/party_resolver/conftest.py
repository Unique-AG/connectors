from collections.abc import AsyncGenerator

import pytest

from backstop_mcp.backstop_client import BackstopClient, create_backstop_client
from tests.party_resolver.helpers import BASE_URL, credential


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    async with create_backstop_client(BASE_URL, credential()) as backstop_client:
        yield backstop_client
