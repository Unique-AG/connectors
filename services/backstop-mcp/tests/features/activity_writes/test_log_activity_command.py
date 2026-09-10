"""Per-kind log commands and the central `LogActivityCommand` switch."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_writes import (
    AuthorDto,
    CallActivityInput,
    EmailActivityInput,
    LogActivityCommand,
    LoggedCallResponse,
    LoggedEmailResponse,
    LoggedMeetingResponse,
    LoggedNoteResponse,
    LoggedTaskResponse,
    MeetingActivityInput,
    NoteActivityInput,
    TaskActivityInput,
    get_log_activity_command_factory,
    get_log_email_command_factory,
    get_log_meeting_or_call_command_factory,
    get_log_note_command_factory,
    get_log_task_command_factory,
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

_AUTHOR = AuthorDto(id="su-author", user_name="bob.smith", name="Bob Smith")
_PARTY_ID = "27871657"
_ORG_ID = "341764767"
_NOTE_ID = "76280387"
_MEETING_ID = "88001122"
_TASK_ID = "99001122"
_EMAIL_ID = "77001122"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _created(resource_type: str, resource_id: str, **attrs: object) -> httpx.Response:
    return httpx.Response(
        201,
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


def make_command(client: BackstopClient) -> LogActivityCommand:
    return get_log_activity_command_factory(
        log_note_command=get_log_note_command_factory(client),
        log_meeting_or_call_command=get_log_meeting_or_call_command_factory(
            client, time_zones_service=time_zones_service(client)
        ),
        log_task_command=get_log_task_command_factory(
            client, system_users_service=system_users_service(client)
        ),
        log_email_command=get_log_email_command_factory(client),
    )


class TestLogActivityCommandDispatch:
    @respx.mock
    async def test_note_posts_nested_notes_using_the_resolved_party_id(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(f"{BASE_URL}/people/{_PARTY_ID}/notes").mock(
            return_value=_created("notes", _NOTE_ID, title="Follow up")
        )
        activity = NoteActivityInput(
            kind="note",
            search_type="people",
            party_id="stale-id",
            title="Follow up",
        )

        result = await make_command(client).run(
            activity=activity, party_id=_PARTY_ID, author=_AUTHOR
        )

        assert isinstance(result, LoggedNoteResponse)
        assert result.id == _NOTE_ID
        assert result.kind == "note"
        assert result.resource_type == "notes"
        assert route.call_count == 1
        body = recorded_json_bodies(route)[0]
        attributes = _attributes(body)
        assert _data(body)["type"] == "notes"
        assert attributes["title"] == "Follow up"
        assert attributes["attachedTo"] == {
            "resourceId": _PARTY_ID,
            "resourceType": "PersonBean",
            "resourceLink": f"/people/{_PARTY_ID}",
        }
        assert object_dict(attributes["author"])["resourceId"] == _AUTHOR.id
        assert "linkedResources" not in attributes

    @respx.mock
    async def test_note_links_a_secondary_party_without_repeating_the_parent(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(f"{BASE_URL}/organizations/{_ORG_ID}/notes").mock(
            return_value=_created("notes", _NOTE_ID)
        )
        activity = NoteActivityInput(
            kind="note",
            search_type="organizations",
            party_id=_ORG_ID,
            title="Visit",
            secondary_party_id=_PARTY_ID,
            secondary_search_type="people",
        )

        await make_command(client).run(
            activity=activity,
            party_id=_ORG_ID,
            author=_AUTHOR,
            secondary_party_id=_PARTY_ID,
        )

        attributes = _attributes(recorded_json_bodies(route)[0])
        assert attributes["linkedResources"] == [
            {
                "resourceId": _PARTY_ID,
                "resourceType": "PersonBean",
                "resourceLink": f"/people/{_PARTY_ID}",
            }
        ]
        assert object_dict(attributes["attachedTo"])["resourceId"] == _ORG_ID

    @respx.mock
    async def test_note_drops_a_secondary_that_repeats_the_parent(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(f"{BASE_URL}/organizations/{_ORG_ID}/notes").mock(
            return_value=_created("notes", _NOTE_ID)
        )
        activity = NoteActivityInput(
            kind="note",
            search_type="organizations",
            party_id=_ORG_ID,
            title="Visit",
            secondary_party_id=_ORG_ID,
            secondary_search_type="organizations",
        )

        await make_command(client).run(
            activity=activity,
            party_id=_ORG_ID,
            author=_AUTHOR,
            secondary_party_id=_ORG_ID,
        )

        assert "linkedResources" not in _attributes(recorded_json_bodies(route)[0])

    @respx.mock
    async def test_meeting_posts_top_level_with_regarding_and_face_to_face(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/time-zones").mock(return_value=_eastern_catalog())
        nested = respx.post(f"{BASE_URL}/organizations/{_ORG_ID}/meetingOrCalls")
        route = respx.post(f"{BASE_URL}/meeting-or-calls").mock(
            return_value=_created("meeting-or-calls", _MEETING_ID, title="Q1 review")
        )
        activity = MeetingActivityInput(
            kind="meeting",
            search_type="organizations",
            party_id=_ORG_ID,
            title="Q1 review",
            time_zone="US/Eastern",
        )

        result = await make_command(client).run(activity=activity, party_id=_ORG_ID, author=_AUTHOR)

        assert isinstance(result, LoggedMeetingResponse)
        assert result.meeting_type == "FACE_TO_FACE"
        assert result.time_zone == "US/Eastern"
        assert result.resource_type == "meeting-or-calls"
        assert nested.call_count == 0
        assert route.call_count == 1
        attributes = _attributes(recorded_json_bodies(route)[0])
        assert attributes["type"] == "FACE_TO_FACE"
        assert attributes["timeZone"] == "US/Eastern"
        assert attributes["regarding"] == {
            "resourceId": _ORG_ID,
            "resourceType": "OrganizationBean",
            "resourceLink": f"/organizations/{_ORG_ID}",
        }
        assert "attachedTo" not in attributes

    @respx.mock
    async def test_call_maps_direction_to_meeting_type(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/time-zones").mock(return_value=_eastern_catalog())
        route = respx.post(f"{BASE_URL}/meeting-or-calls").mock(
            return_value=_created("meeting-or-calls", _MEETING_ID)
        )
        activity = CallActivityInput(
            kind="call",
            search_type="people",
            party_id=_PARTY_ID,
            title="Check in",
            time_zone="US/Eastern",
            direction="PHONE_IN",
        )

        result = await make_command(client).run(
            activity=activity, party_id=_PARTY_ID, author=_AUTHOR
        )

        assert isinstance(result, LoggedCallResponse)
        assert result.meeting_type == "PHONE_IN"
        assert _attributes(recorded_json_bodies(route)[0])["type"] == "PHONE_IN"

    @respx.mock
    async def test_task_posts_name_and_send_notification_without_author_or_tags(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/system-users").mock(return_value=_assignee_catalog())
        route = respx.post(f"{BASE_URL}/tasks").mock(
            return_value=_created("tasks", _TASK_ID, name="Send deck")
        )
        activity = TaskActivityInput(
            kind="task",
            search_type="people",
            party_id=_PARTY_ID,
            title="Send deck",
            assigned_user="jdoe",
        )

        result = await make_command(client).run(
            activity=activity, party_id=_PARTY_ID, author=_AUTHOR
        )

        assert isinstance(result, LoggedTaskResponse)
        assert result.send_notification is False
        attributes = _attributes(recorded_json_bodies(route)[0])
        assert attributes["name"] == "Send deck"
        assert attributes["sendNotification"] is False
        assert object_dict(attributes["assignedUser"])["resourceId"] == "su-assignee"
        assert "author" not in attributes
        assert "effectiveDate" not in attributes
        assert "activityTags" not in attributes
        assert "relationships" not in _data(recorded_json_bodies(route)[0])

    @respx.mock
    async def test_email_posts_metadata_stub(self, client: BackstopClient) -> None:
        route = respx.post(f"{BASE_URL}/emails").mock(
            return_value=_created("emails", _EMAIL_ID, displaySubject="Intro")
        )
        activity = EmailActivityInput(
            kind="email",
            search_type="people",
            party_id=_PARTY_ID,
            display_subject="Intro",
        )

        result = await make_command(client).run(
            activity=activity, party_id=_PARTY_ID, author=_AUTHOR
        )

        assert isinstance(result, LoggedEmailResponse)
        assert result.title == "Intro"
        attributes = _attributes(recorded_json_bodies(route)[0])
        assert attributes["displaySubject"] == "Intro"
        assert attributes["resources"] == [
            {
                "resourceId": _PARTY_ID,
                "resourceType": "PersonBean",
                "resourceLink": f"/people/{_PARTY_ID}",
            }
        ]
        assert object_dict(attributes["createdBy"])["resourceId"] == _AUTHOR.id
