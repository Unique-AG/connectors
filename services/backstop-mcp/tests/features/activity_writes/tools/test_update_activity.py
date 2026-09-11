"""`update_activity`: dispatch to the matching PATCH command."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_writes import (
    UpdateActivityCommand,
    UpdatedActivityResponse,
    UpdateNoteInput,
    get_update_activity_command_factory,
    get_update_document_command_factory,
    get_update_email_command_factory,
    get_update_meeting_or_call_command_factory,
    get_update_note_command_factory,
    get_update_task_command_factory,
)
from backstop_mcp.features.activity_writes.tools.update_activity import update_activity
from backstop_mcp.server.tools import TOOLS
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    recorded_json_bodies,
    system_users_service,
    time_zones_service,
)
from tests.server.tools.helpers import object_dict, tool_model

_NOTE_ID = "76280387"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> UpdateActivityCommand:
    return get_update_activity_command_factory(
        update_note_command=get_update_note_command_factory(client),
        update_meeting_or_call_command=get_update_meeting_or_call_command_factory(
            client, time_zones_service=time_zones_service(client)
        ),
        update_task_command=get_update_task_command_factory(
            client, system_users_service=system_users_service(client)
        ),
        update_email_command=get_update_email_command_factory(client),
        update_document_command=get_update_document_command_factory(client),
    )


class TestUpdateActivity:
    def test_is_registered(self) -> None:
        assert update_activity in TOOLS

    @respx.mock
    async def test_patches_the_note(self, client: BackstopClient) -> None:
        route = respx.patch(f"{BASE_URL}/notes/{_NOTE_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": _NOTE_ID,
                        "type": "notes",
                        "attributes": {"title": "Corrected"},
                    }
                },
            )
        )

        result = tool_model(
            await update_activity(
                activity=UpdateNoteInput(kind="note", activity_id=_NOTE_ID, title="Corrected"),
                update_activity_command=make_command(client),
            ),
            UpdatedActivityResponse,
        )

        assert result.id == _NOTE_ID
        assert result.resource_type == "notes"
        assert route.call_count == 1
        attributes = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        assert attributes == {"title": "Corrected"}
