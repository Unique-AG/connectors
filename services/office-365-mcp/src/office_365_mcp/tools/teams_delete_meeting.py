import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.online_meeting import OnlineMeeting
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared import identity
from office_365_mcp.shared.handles import MeetingHandle, meeting_handle
from office_365_mcp.shared.meetings import organized_by, resolve_meeting
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_delete_meeting"

STEP_DELETE = "delete_meeting"

GRAPH_PERMISSIONS: tuple[str, ...] = ("OnlineMeetings.ReadWrite", identity.GRAPH_PERMISSION)

CHANGE_SHOWN_BY: tuple[str, ...] = ("teams_read_meeting",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "meeting_uri": "teams:///meetings/https%3A%2F%2Fteams.microsoft.invalid%2Fl%2Fmeetup-join"
    + "%2F19%253ameeting_TjAwMDAwMDAwMDAwMA%2540thread.v2%2F0",
}

_AGREE = "delete"
_DECLINE = "do not delete"
_NOTHING_DELETED = "No meeting was deleted."
_FAILS_THE_SAME_WAY = (
    "If you call this tool again with the same arguments, the call will fail the same way."
)

_DESCRIPTION = """\
Deletes one Teams online meeting that the signed-in user organizes. This tool sends its change \
to the Teams online meeting only, and never to a calendar event. For a meeting on a calendar, use \
outlook_cancel_event. This tool deletes the meeting immediately, and nothing here can restore it.

Notes:
- This tool asks the user to agree before it deletes anything, every time. This tool deletes \
nothing unless the user agrees.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
teams_read_meeting does not already show the change.
"""

_NOT_A_MEETING_HANDLE = (
    "teams_delete_meeting takes the `meeting_uri` handle from teams_list_chats, and this value is "
    + "not one. A meeting handle has exactly one shape:\n"
    + "  teams:///meetings/{join_web_url}\n"
    + "with the join URL percent-encoded. Copy the `meeting_uri` of a tool result word for word. "
    + f"{_NOTHING_DELETED} {_FAILS_THE_SAME_WAY}"
)

_NO_SUCH_MEETING = (
    "Microsoft 365 has no meeting with this handle that the signed-in user can see. "
    + f"{_NOTHING_DELETED} If the meeting is already deleted, no meeting is left to delete. Do "
    + "not change the handle by hand. "
    + f"Call teams_list_chats and use the `meeting_uri` that it reports. {_FAILS_THE_SAME_WAY}"
)

_NOT_THE_ORGANIZER = (
    "Microsoft 365 does not name the signed-in user as the organizer of this meeting. This tool "
    + f"deletes only a meeting that the signed-in user organizes. {_NOTHING_DELETED} "
    + _FAILS_THE_SAME_WAY
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this meeting when this tool sent the delete. "
    + f"{_NOTHING_DELETED} The meeting was there a moment before, so a person or an earlier call "
    + "probably deleted it. Call teams_read_meeting to see if the meeting is still there."
)


class DeletedMeeting(BaseModel):
    meeting_uri: str = Field(
        description=(
            "The handle that this call was given, echoed back from `meeting_uri`. It names the "
            + "meeting that this call deleted."
        )
    )
    subject: str | None = Field(
        description=(
            "The subject that the meeting had immediately before the delete, as Microsoft 365 "
            + "held it. Null when the meeting had no subject."
        )
    )
    start: datetime | None = Field(
        description=(
            "When the meeting was due to start, in UTC, as Microsoft 365 held it immediately "
            + "before the delete. Null when Microsoft 365 gave no start."
        )
    )


async def delete_meeting(
    client: GraphServiceClient, *, meeting_uri: str, confirm: Confirm
) -> DeletedMeeting | InputRequiredResult:
    handle = meeting_handle(meeting_uri)
    if handle is None:
        raise ToolError(_NOT_A_MEETING_HANDLE)

    found: OnlineMeeting | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        found = await resolve_meeting(client, handle)
        if found is None or found.id is None:
            refused = _NO_SUCH_MEETING
        elif not organized_by(found, await identity.signed_in_user(client)):
            refused = _NOT_THE_ORGANIZER
        else:
            with not_graph():
                answer = await confirm(_question(found), _about(handle))
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
            if refused is None and asked is None:
                with graph_step(STEP_DELETE):
                    await client.me.online_meetings.by_online_meeting_id(found.id).delete(
                        request_configuration=RequestConfiguration[QueryParameters](
                            options=no_retry()
                        )
                    )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert found is not None, "a delete that nothing refused had no meeting to delete"
    return DeletedMeeting(
        meeting_uri=handle.uri, subject=found.subject, start=found.start_date_time
    )


def _about(handle: MeetingHandle) -> str:
    return hashlib.sha256(json.dumps([handle.uri]).encode()).hexdigest()


def _question(meeting: OnlineMeeting) -> str:
    name = repr(cut_for_a_question(meeting.subject)) if meeting.subject else "that has no subject"
    start = meeting.start_date_time
    when = "" if start is None else f", which starts at {start.isoformat()}"
    return f"Delete the Teams meeting {name}{when}? Nothing here can restore the meeting."


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Delete a Teams Meeting",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def teams_delete_meeting(
        meeting_uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The meeting to delete, as the `meeting_uri` handle from teams_list_chats: "
                    + "`teams:///meetings/{join_web_url}`. Copy it word for word. A "
                    + "`teams:///transcripts/...` handle is not valid here."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedMeeting | InputRequiredResult:
        return await delete_meeting(client, meeting_uri=meeting_uri, confirm=a_person_agrees(ctx))
