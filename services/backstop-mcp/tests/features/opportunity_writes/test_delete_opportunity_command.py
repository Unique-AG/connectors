"""`DeleteOpportunityCommand` hard-deletes an opportunity with no body."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunity_writes import (
    DeletedOpportunityResponse,
    DeleteOpportunityInput,
    get_delete_opportunity_command_factory,
)
from tests.helpers import BASE_URL, client_factory, credential, recorded_requests

_ID = "5755101"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


class TestDeleteOpportunityCommand:
    @respx.mock
    async def test_delete_sends_no_body_and_no_schema(self, client: BackstopClient) -> None:
        route = respx.delete(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(204, content=b"")
        )
        spy = AsyncMock(wraps=client.delete)

        with patch.object(client, "delete", spy):
            result = await get_delete_opportunity_command_factory(client).run(
                opportunity=DeleteOpportunityInput(opportunity_id=_ID)
            )

        assert isinstance(result, DeletedOpportunityResponse)
        assert result.id == _ID
        assert result.resource_type == "opportunities"
        assert result.permanent is True
        assert route.call_count == 1
        request = recorded_requests(route.calls)[0]
        assert request.method == "DELETE"
        assert request.content in (b"", b"null")
        spy.assert_awaited_once_with(f"/opportunities/{_ID}")
