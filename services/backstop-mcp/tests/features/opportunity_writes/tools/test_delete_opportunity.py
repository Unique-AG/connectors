"""`delete_opportunity`: format a confirmation prompt, then delete unless elicitation
was declined.
"""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from mcp.types import ElicitRequestFormParams, ElicitResult, InputRequiredResult

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.elicitation_utils import (
    DELETE,
    DELETION_INPUT_KEY,
    DeletionNeedsConfirmationResponse,
)
from backstop_mcp.features.opportunity_writes import (
    DeletedOpportunityResponse,
    DeleteOpportunityInput,
    get_delete_opportunity_command_factory,
)
from backstop_mcp.features.opportunity_writes.tools.delete_opportunity import delete_opportunity
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import (
    ctx_deletion_answer,
    ctx_handshake_era,
    ctx_never_elicit,
    ctx_no_elicitation_capability,
)
from tests.helpers import BASE_URL, client_factory, credential
from tests.server.tools.helpers import tool_model

_ID = "5755101"
_NAME = "Koch - CATS Select"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _opportunity_document(*, name: str = _NAME) -> dict[str, object]:
    return {
        "data": {
            "id": _ID,
            "type": "opportunities",
            "attributes": {"name": name},
        }
    }


class TestDeleteOpportunity:
    def test_is_registered(self) -> None:
        assert delete_opportunity in TOOLS

    @respx.mock
    async def test_deletes_when_the_client_cannot_elicit(self, client: BackstopClient) -> None:
        preview = respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(200, json=_opportunity_document())
        )
        route = respx.delete(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        result = tool_model(
            await delete_opportunity(
                ctx_no_elicitation_capability(),
                opportunity=DeleteOpportunityInput(opportunity_id=_ID),
                client=client,
                delete_opportunity_command=get_delete_opportunity_command_factory(client),
            ),
            DeletedOpportunityResponse,
        )

        assert result.id == _ID
        assert result.resource_type == "opportunities"
        assert result.permanent is True
        assert preview.call_count == 0
        assert route.call_count == 1

    @respx.mock
    async def test_reads_the_opportunity_then_asks_without_deleting(
        self, client: BackstopClient
    ) -> None:
        preview = respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(200, json=_opportunity_document())
        )
        route = respx.delete(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        result = await delete_opportunity(
            ctx_never_elicit(),
            opportunity=DeleteOpportunityInput(opportunity_id=_ID),
            client=client,
            delete_opportunity_command=get_delete_opportunity_command_factory(client),
        )

        assert isinstance(result, InputRequiredResult)
        assert result.input_requests is not None
        params = result.input_requests[DELETION_INPUT_KEY].params
        assert isinstance(params, ElicitRequestFormParams)
        assert _ID in params.message
        assert _NAME in params.message
        assert preview.call_count == 1
        assert route.call_count == 0

    @respx.mock
    async def test_handshake_era_returns_needs_confirmation_without_deleting(
        self, client: BackstopClient
    ) -> None:
        preview = respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(200, json=_opportunity_document())
        )
        route = respx.delete(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        result = tool_model(
            await delete_opportunity(
                ctx_handshake_era(),
                opportunity=DeleteOpportunityInput(opportunity_id=_ID),
                client=client,
                delete_opportunity_command=get_delete_opportunity_command_factory(client),
            ),
            DeletionNeedsConfirmationResponse,
        )

        assert result.status == "needs_confirmation"
        assert _NAME in result.preview
        assert preview.call_count == 1
        assert route.call_count == 0

    @respx.mock
    async def test_handshake_era_deletes_when_confirm_is_true(
        self, client: BackstopClient
    ) -> None:
        route = respx.delete(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        result = tool_model(
            await delete_opportunity(
                ctx_handshake_era(),
                opportunity=DeleteOpportunityInput(opportunity_id=_ID, confirm=True),
                client=client,
                delete_opportunity_command=get_delete_opportunity_command_factory(client),
            ),
            DeletedOpportunityResponse,
        )

        assert result.id == _ID
        assert route.call_count == 1

    @respx.mock
    async def test_confirmed_elicitation_deletes(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(200, json=_opportunity_document())
        )
        route = respx.delete(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        result = tool_model(
            await delete_opportunity(
                ctx_deletion_answer(ElicitResult(action="accept", content={"choice": DELETE})),
                opportunity=DeleteOpportunityInput(opportunity_id=_ID),
                client=client,
                delete_opportunity_command=get_delete_opportunity_command_factory(client),
            ),
            DeletedOpportunityResponse,
        )

        assert result.id == _ID
        assert result.permanent is True
        assert result.resource_type == "opportunities"
        assert route.call_count == 1

    @respx.mock
    async def test_declined_elicitation_does_not_write(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(200, json=_opportunity_document())
        )
        route = respx.delete(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        with pytest.raises(ToolError, match="not confirmed") as raised:
            await delete_opportunity(
                ctx_deletion_answer(ElicitResult(action="decline")),
                opportunity=DeleteOpportunityInput(opportunity_id=_ID),
                client=client,
                delete_opportunity_command=get_delete_opportunity_command_factory(client),
            )

        assert "Nothing was deleted" in str(raised.value)
        assert route.call_count == 0
