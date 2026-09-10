"""Per-kind update commands and the central `UpdateActivityCommand` switch."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_writes import (
    UpdateActivityCommand,
    UpdateCallInput,
    UpdatedActivityResponse,
    UpdateDocumentInput,
    UpdateEmailInput,
    UpdateMeetingInput,
    UpdateNoteInput,
    UpdateTaskInput,
    get_update_activity_command_factory,
    get_update_document_command_factory,
    get_update_email_command_factory,
    get_update_meeting_or_call_command_factory,
    get_update_note_command_factory,
    get_update_task_command_factory,
)
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    recorded_json_bodies,
    resource,
    system_users_service,
    time_zones_service,
)
from tests.server.tools.helpers import object_dict

_NOTE_ID = "76280387"
_MEETING_ID = "88001122"
_TASK_ID = "99001122"
_EMAIL_ID = "77001122"
_DOC_ID = "88002233"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _updated(resource_type: str, resource_id: str, **attrs: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": {"id": resource_id, "type": resource_type, "attributes": attrs}},
    )


def _collection_page(*items: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(items), "links": {"next": None}})


def _eastern_catalog() -> httpx.Response:
    return _collection_page(
        resource(
            "america_new_york",
            "time-zones",
            name="Eastern Standard Time",
            shortName="US/Eastern",
        )
    )


def _assignee_catalog() -> httpx.Response:
    return _collection_page(
        resource("su-assignee", "system-users", name="Jane Doe", userName="jdoe")
    )


def _data(body: dict[str, object]) -> dict[str, object]:
    return object_dict(body["data"])


def _attributes(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["attributes"])


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


class TestUpdateActivityCommand:
    @respx.mock
    async def test_note_patches_title_and_omits_unchanged_fields(
        self, client: BackstopClient
    ) -> None:
        route = respx.patch(f"{BASE_URL}/notes/{_NOTE_ID}").mock(
            return_value=_updated("notes", _NOTE_ID, title="Corrected")
        )

        result = await make_command(client).run(
            activity=UpdateNoteInput(kind="note", activity_id=_NOTE_ID, title="Corrected")
        )

        assert isinstance(result, UpdatedActivityResponse)
        assert result.id == _NOTE_ID
        assert result.resource_type == "notes"
        body = recorded_json_bodies(route)[0]
        assert _data(body)["type"] == "notes"
        assert _data(body)["id"] == _NOTE_ID
        assert _attributes(body) == {"title": "Corrected"}
        assert "relationships" not in _data(body)

    @respx.mock
    async def test_note_accepts_a_matching_history_handle(self, client: BackstopClient) -> None:
        route = respx.patch(f"{BASE_URL}/notes/{_NOTE_ID}").mock(
            return_value=_updated("notes", _NOTE_ID)
        )

        await make_command(client).run(
            activity=UpdateNoteInput(
                kind="note", activity_id=f"notes_{_NOTE_ID}", title="Corrected"
            )
        )

        assert route.call_count == 1

    @respx.mock
    async def test_rejects_a_handle_for_a_different_collection(
        self, client: BackstopClient
    ) -> None:
        route = respx.patch(url__regex=r".*").mock(return_value=_updated("notes", _NOTE_ID))

        with pytest.raises(ToolError, match="meeting-or-calls"):
            await make_command(client).run(
                activity=UpdateNoteInput(
                    kind="note",
                    activity_id=f"meeting-or-calls_{_MEETING_ID}",
                    title="Corrected",
                )
            )

        assert route.call_count == 0

    @respx.mock
    async def test_meeting_patches_location_without_resolving_a_time_zone(
        self, client: BackstopClient
    ) -> None:
        route = respx.patch(f"{BASE_URL}/meeting-or-calls/{_MEETING_ID}").mock(
            return_value=_updated("meeting-or-calls", _MEETING_ID)
        )

        result = await make_command(client).run(
            activity=UpdateMeetingInput(
                kind="meeting", activity_id=_MEETING_ID, location="Boardroom"
            )
        )

        assert result.resource_type == "meeting-or-calls"
        attributes = _attributes(recorded_json_bodies(route)[0])
        assert attributes == {"location": "Boardroom", "type": "FACE_TO_FACE"}
        assert "timeZone" not in attributes

    @respx.mock
    async def test_call_patches_direction_and_resolved_time_zone(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/time-zones").mock(return_value=_eastern_catalog())
        route = respx.patch(f"{BASE_URL}/meeting-or-calls/{_MEETING_ID}").mock(
            return_value=_updated("meeting-or-calls", _MEETING_ID)
        )

        await make_command(client).run(
            activity=UpdateCallInput(
                kind="call",
                activity_id=_MEETING_ID,
                direction="PHONE_IN",
                time_zone="US/Eastern",
            )
        )

        attributes = _attributes(recorded_json_bodies(route)[0])
        assert attributes["type"] == "PHONE_IN"
        assert attributes["timeZone"] == "US/Eastern"

    @respx.mock
    async def test_empty_tag_tuple_clears_activity_tags(self, client: BackstopClient) -> None:
        route = respx.patch(f"{BASE_URL}/emails/{_EMAIL_ID}").mock(
            return_value=_updated("emails", _EMAIL_ID)
        )

        await make_command(client).run(
            activity=UpdateEmailInput(kind="email", activity_id=_EMAIL_ID, activity_tag_ids=())
        )

        body = recorded_json_bodies(route)[0]
        assert _attributes(body) == {}
        relationships = object_dict(_data(body)["relationships"])
        assert object_dict(relationships["activityTags"]) == {"data": []}

    @respx.mock
    async def test_email_does_not_send_created_by(self, client: BackstopClient) -> None:
        route = respx.patch(f"{BASE_URL}/emails/{_EMAIL_ID}").mock(
            return_value=_updated("emails", _EMAIL_ID)
        )

        await make_command(client).run(
            activity=UpdateEmailInput(
                kind="email", activity_id=_EMAIL_ID, display_subject="Revised"
            )
        )

        attributes = _attributes(recorded_json_bodies(route)[0])
        assert attributes == {"displaySubject": "Revised"}
        assert "createdBy" not in attributes

    @respx.mock
    async def test_task_resolves_assigned_user(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/system-users").mock(return_value=_assignee_catalog())
        route = respx.patch(f"{BASE_URL}/tasks/{_TASK_ID}").mock(
            return_value=_updated("tasks", _TASK_ID)
        )

        await make_command(client).run(
            activity=UpdateTaskInput(kind="task", activity_id=_TASK_ID, assigned_user="jdoe")
        )

        attributes = _attributes(recorded_json_bodies(route)[0])
        assert object_dict(attributes["assignedUser"])["resourceId"] == "su-assignee"
        assert "name" not in attributes

    @respx.mock
    async def test_document_patches_metadata(self, client: BackstopClient) -> None:
        route = respx.patch(f"{BASE_URL}/documents/{_DOC_ID}").mock(
            return_value=_updated("documents", _DOC_ID)
        )

        result = await make_command(client).run(
            activity=UpdateDocumentInput(kind="document", activity_id=_DOC_ID, title="Revised memo")
        )

        assert result.resource_type == "documents"
        assert _attributes(recorded_json_bodies(route)[0]) == {"title": "Revised memo"}
