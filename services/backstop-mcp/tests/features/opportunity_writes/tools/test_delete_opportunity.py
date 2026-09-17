"""`delete_opportunity`: format a confirmation prompt, then delete unless elicitation
was declined.
"""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.elicitation_utils import DELETE, KEEP, DeletionChoice
from backstop_mcp.features.opportunity_writes import (
    DeletedOpportunityResponse,
    DeleteOpportunityInput,
    get_delete_opportunity_command_factory,
)
from backstop_mcp.features.opportunity_writes.tools.delete_opportunity import delete_opportunity
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import (
    FakeContext,
    as_context,
    ctx_accept,
    ctx_cancel,
    ctx_decline,
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


def ctx_capture(prompts: list[str]) -> Context:
    """Accepts the delete, recording the prompt the user was shown."""

    async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[object]:
        _ = response_type
        prompts.append(message)
        return AcceptedElicitation(data=DeletionChoice(choice=DELETE))

    return as_context(FakeContext(elicit))


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
    async def test_reads_the_opportunity_and_shows_it_before_deleting(
        self, client: BackstopClient
    ) -> None:
        preview = respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(200, json=_opportunity_document())
        )
        route = respx.delete(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(204)
        )
        prompts: list[str] = []

        result = tool_model(
            await delete_opportunity(
                ctx_capture(prompts),
                opportunity=DeleteOpportunityInput(opportunity_id=_ID),
                client=client,
                delete_opportunity_command=get_delete_opportunity_command_factory(client),
            ),
            DeletedOpportunityResponse,
        )

        assert result.id == _ID
        assert len(prompts) == 1
        assert _ID in prompts[0]
        assert _NAME in prompts[0]
        assert preview.call_count == 1
        assert route.call_count == 1

    @respx.mock
    async def test_keeping_the_record_does_not_write(self, client: BackstopClient) -> None:
        preview = respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(200, json=_opportunity_document())
        )
        route = respx.delete(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        with pytest.raises(ToolError, match="not confirmed"):
            await delete_opportunity(
                ctx_accept(DeletionChoice(choice=KEEP)),
                opportunity=DeleteOpportunityInput(opportunity_id=_ID),
                client=client,
                delete_opportunity_command=get_delete_opportunity_command_factory(client),
            )

        assert preview.call_count == 1
        assert route.call_count == 0

    @respx.mock
    async def test_cancelled_elicitation_does_not_write(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(200, json=_opportunity_document())
        )
        route = respx.delete(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        with pytest.raises(ToolError, match="not confirmed"):
            await delete_opportunity(
                ctx_cancel(),
                opportunity=DeleteOpportunityInput(opportunity_id=_ID),
                client=client,
                delete_opportunity_command=get_delete_opportunity_command_factory(client),
            )

        assert route.call_count == 0

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
                ctx_accept(DeletionChoice(choice=DELETE)),
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
                ctx_decline(),
                opportunity=DeleteOpportunityInput(opportunity_id=_ID),
                client=client,
                delete_opportunity_command=get_delete_opportunity_command_factory(client),
            )

        assert "Nothing was deleted" in str(raised.value)
        assert route.call_count == 0
