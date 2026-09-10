"""`delete_activity`: dispatch to the hard-delete command."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_writes import (
    DeleteActivityInput,
    DeletedActivityResponse,
    get_delete_activity_command_factory,
)
from backstop_mcp.features.activity_writes.tools.delete_activity import delete_activity
from backstop_mcp.server.tools import TOOLS
from tests.helpers import BASE_URL, client_factory, credential
from tests.server.tools.helpers import tool_model

_NOTE_ID = "76280387"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


class TestDeleteActivity:
    def test_is_registered(self) -> None:
        assert delete_activity in TOOLS

    @respx.mock
    async def test_hard_deletes_the_note(self, client: BackstopClient) -> None:
        route = respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(return_value=httpx.Response(204))

        result = tool_model(
            await delete_activity(
                activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID),
                delete_activity_command=get_delete_activity_command_factory(client),
            ),
            DeletedActivityResponse,
        )

        assert result.id == _NOTE_ID
        assert result.resource_type == "notes"
        assert result.permanent is True
        assert route.call_count == 1
