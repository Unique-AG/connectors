"""`DeleteActivityCommand` hard-deletes every activity collection."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.activity_writes import (
    DeleteActivityInput,
    DeletedActivityResponse,
    get_delete_activity_command_factory,
)
from tests.helpers import BASE_URL, client_factory, credential

_NOTE_ID = "76280387"
_EMAIL_ID = "77001122"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


class TestDeleteActivityCommand:
    @respx.mock
    async def test_deletes_a_note_and_marks_it_permanent(self, client: BackstopClient) -> None:
        route = respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(return_value=httpx.Response(204))

        result = await get_delete_activity_command_factory(client).run(
            activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID)
        )

        assert isinstance(result, DeletedActivityResponse)
        assert result.id == _NOTE_ID
        assert result.resource_type == "notes"
        assert result.permanent is True
        assert route.call_count == 1

    @respx.mock
    @pytest.mark.parametrize("handle", [f"emails_{_EMAIL_ID}", f"email_{_EMAIL_ID}"])
    async def test_accepts_an_email_history_handle(
        self, client: BackstopClient, handle: str
    ) -> None:
        route = respx.delete(f"{BASE_URL}/emails/{_EMAIL_ID}").mock(
            return_value=httpx.Response(204)
        )

        result = await get_delete_activity_command_factory(client).run(
            activity=DeleteActivityInput(kind="email", activity_id=handle)
        )

        assert result.id == _EMAIL_ID
        assert result.resource_type == "emails"
        assert route.call_count == 1

    @respx.mock
    async def test_rejects_a_slash_in_the_activity_id(self, client: BackstopClient) -> None:
        route = respx.delete(url__regex=r".*").mock(return_value=httpx.Response(204))

        with pytest.raises(ToolError, match="not a Backstop activity id"):
            await get_delete_activity_command_factory(client).run(
                activity=DeleteActivityInput(kind="note", activity_id="notes/76280387")
            )

        assert route.call_count == 0

    @respx.mock
    async def test_missing_activity_404_does_not_point_at_list_activity_tags(
        self, client: BackstopClient
    ) -> None:
        title = f"Resource notes not found by id {_NOTE_ID}"
        respx.delete(f"{BASE_URL}/notes/{_NOTE_ID}").mock(
            return_value=httpx.Response(
                404,
                json={"errors": [{"code": "ResourceNotFoundException", "title": title}]},
            )
        )

        with pytest.raises(BackstopApiError, match=title) as raised:
            await get_delete_activity_command_factory(client).run(
                activity=DeleteActivityInput(kind="note", activity_id=_NOTE_ID)
            )

        assert raised.value.status_code == 404
        assert "list_activity_tags" not in str(raised.value)
