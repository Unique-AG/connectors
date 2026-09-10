"""`log_activity`: party resolve then the matching create command."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_writes import (
    LogActivityCommand,
    LoggedNoteResponse,
    NoteActivityInput,
    get_log_activity_command_factory,
    get_log_email_command_factory,
    get_log_meeting_or_call_command_factory,
    get_log_note_command_factory,
    get_log_task_command_factory,
)
from backstop_mcp.features.activity_writes.tools.log_activity import log_activity
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.features.system_users import SystemUserDto
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import ctx_never_elicit, make_resolve_party_query
from tests.helpers import (
    BASE_URL,
    client_factory,
    collection,
    credential,
    recorded_json_bodies,
    system_users_service,
    time_zones_service,
)
from tests.server.tools.helpers import object_dict, tool_model, tool_model_union

_PARTY_ID = "27871657"
_NOTE_ID = "76280387"
_CALLER = SystemUserDto(id="su-author", user_name="bob.smith", name="Bob Smith")


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


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


def _created(resource_type: str, resource_id: str, **attrs: object) -> httpx.Response:
    return httpx.Response(
        201,
        json={"data": {"id": resource_id, "type": resource_type, "attributes": attrs}},
    )


class TestLogActivity:
    def test_is_registered(self) -> None:
        assert log_activity in TOOLS

    @respx.mock
    async def test_resolves_the_party_then_posts_the_note(self, client: BackstopClient) -> None:
        route = respx.post(f"{BASE_URL}/people/{_PARTY_ID}/notes").mock(
            return_value=_created("notes", _NOTE_ID, title="Follow up")
        )

        result = tool_model(
            await log_activity(
                ctx_never_elicit(),
                activity=NoteActivityInput(
                    kind="note",
                    search_type="people",
                    party_id=_PARTY_ID,
                    title="Follow up",
                ),
                resolve_party_query=make_resolve_party_query(client),
                log_activity_command=make_command(client),
                caller=_CALLER,
            ),
            LoggedNoteResponse,
        )

        assert result.id == _NOTE_ID
        assert result.kind == "note"
        assert route.call_count == 1
        attributes = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        assert object_dict(attributes["author"])["resourceId"] == _CALLER.id
        assert object_dict(attributes["attachedTo"])["resourceId"] == _PARTY_ID

    @respx.mock
    async def test_an_unresolved_search_is_not_found(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )
        respx.get(f"{BASE_URL}/people").mock(return_value=httpx.Response(200, json=collection()))

        result = tool_model_union(
            await log_activity(
                ctx_never_elicit(),
                activity=NoteActivityInput(
                    kind="note",
                    search_type="people",
                    search="Nobody",
                    title="Follow up",
                ),
                resolve_party_query=make_resolve_party_query(client),
                log_activity_command=make_command(client),
                caller=_CALLER,
            ),
            LoggedNoteResponse | NotFoundResponse,
        )

        assert isinstance(result, NotFoundResponse)
        assert result.query == "Nobody"
        assert result.scope == "people"
