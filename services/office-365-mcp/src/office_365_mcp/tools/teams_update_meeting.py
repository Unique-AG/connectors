import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.identity import Identity
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.generated.models.meeting_participant_info import MeetingParticipantInfo
from msgraph.generated.models.meeting_participants import MeetingParticipants
from msgraph.generated.models.online_meeting import OnlineMeeting
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared import identity
from office_365_mcp.shared.calendar import counted_people
from office_365_mcp.shared.handles import MeetingHandle, meeting_handle
from office_365_mcp.shared.meetings import organized_by, resolve_meeting
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_update_meeting"

STEP_UPDATE = "update_meeting"

GRAPH_PERMISSIONS: tuple[str, ...] = ("OnlineMeetings.ReadWrite", identity.GRAPH_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "meeting_uri": "teams:///meetings/https%3A%2F%2Fteams.microsoft.invalid%2Fl%2Fmeetup-join"
    + "%2F19%253ameeting_TjAwMDAwMDAwMDAwMA%2540thread.v2%2F0",
    "subject": "Pricing review (moved)",
}

_AGREE = "change"
_DECLINE = "do not change"
_NOTHING_CHANGED = "No meeting was changed."
_FAILS_THE_SAME_WAY = (
    "If you call this tool again with the same arguments, the call will fail the same way."
)

_DESCRIPTION = """\
Changes the subject, the time, or the attendee list of one Teams online meeting that the \
signed-in user organizes. This tool sends its change to the Teams online meeting only, and never \
to a calendar event. For a meeting on a calendar, use outlook_update_event. teams_read_meeting \
shows the meeting as it is now.

Notes:
- This tool asks the user to agree before it changes anything, every time. This tool changes \
nothing unless the user agrees.
- Before you change `attendees`, read the current list with teams_read_meeting. The new list must \
hold everyone who stays.
- This call is safe to repeat after a timeout. A second call with the same arguments leaves the \
meeting in the same state.
"""

_NOT_A_MEETING_HANDLE = (
    "teams_update_meeting takes the `meeting_uri` handle from teams_list_chats, and this value is "
    + "not one. A meeting handle has exactly one shape:\n"
    + "  teams:///meetings/{join_web_url}\n"
    + "with the join URL percent-encoded. Copy the `meeting_uri` of a tool result word for word. "
    + f"{_NOTHING_CHANGED} {_FAILS_THE_SAME_WAY}"
)

_NO_SUCH_MEETING = (
    "Microsoft 365 has no meeting with this handle that the signed-in user can see. "
    + f"{_NOTHING_CHANGED} Do not change the handle by hand. Call teams_list_chats and use the "
    + f"`meeting_uri` that it reports. {_FAILS_THE_SAME_WAY}"
)

_NOT_THE_ORGANIZER = (
    "Microsoft 365 does not name the signed-in user as the organizer of this meeting. This tool "
    + f"changes only a meeting that the signed-in user organizes. {_NOTHING_CHANGED} "
    + _FAILS_THE_SAME_WAY
)

_NOTHING_TO_CHANGE = (
    "teams_update_meeting received no change. The call left out `subject`, `starts_at` with "
    + f"`ends_at`, and `attendees`. {_NOTHING_CHANGED} Give at least one of them. To see what "
    + "the meeting holds now, call teams_read_meeting first."
)

_ONE_TIME_ONLY = (
    "teams_update_meeting received `starts_at` or `ends_at` without the other. Microsoft 365 "
    + f"takes a new time only as a start and an end together. {_NOTHING_CHANGED} Give both, or "
    + "omit both to keep the current time."
)

_ENDS_BEFORE_IT_STARTS = (
    "teams_update_meeting received an `ends_at` that is not after `starts_at`. A meeting must "
    + "end after it starts. A meeting that runs past midnight ends on the next day. Make sure "
    + f"that the date of `ends_at` is correct. {_NOTHING_CHANGED} {_FAILS_THE_SAME_WAY}"
)

_LEFT_OUT = "A person who is not in the new list is no longer an attendee."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this meeting when this tool sent the change. "
    + f"{_NOTHING_CHANGED} The meeting was there a moment before, so a person or another call "
    + "probably deleted it. Call teams_read_meeting to see if the meeting is still there."
)


def _no_offset(argument: str, value: str) -> str:
    return (
        f"teams_update_meeting received {value!r} in `{argument}`. This time has no offset, so it "
        + "does not name one instant. Add the offset of the zone of the user, for example "
        + "`2026-03-02T14:00:00+01:00`, or add `Z` for UTC. If the zone is not clear, ask the "
        + f"user. {_NOTHING_CHANGED} {_FAILS_THE_SAME_WAY}"
    )


def _not_a_time(argument: str, value: str) -> str:
    return (
        f"teams_update_meeting received {value!r} in `{argument}`. This value is not an ISO-8601 "
        + "date and time. Write the date, the time, and an offset, for example "
        + "`2026-03-02T14:00:00+01:00`. If the day or the hour is ambiguous, ask the user. "
        + f"{_NOTHING_CHANGED} {_FAILS_THE_SAME_WAY}"
    )


class UpdatedMeeting(BaseModel):
    meeting_uri: str = Field(
        description=(
            "The handle of the meeting that this call changed, echoed back from `meeting_uri`. "
            + "Pass it to teams_read_meeting to see the meeting as it is now."
        )
    )
    subject: str | None = Field(
        description=(
            "The subject that Microsoft 365 holds for the meeting after this change, read from "
            + "the answer of Microsoft 365. Null when Microsoft 365 holds no subject."
        )
    )
    start: datetime | None = Field(
        description=(
            "When the meeting starts after this change, in UTC, as Microsoft 365 holds it. "
            + "Report this time to the user in the zone of the user. Null when Microsoft 365 gave "
            + "no start."
        )
    )
    end: datetime | None = Field(
        description=(
            "When the meeting ends after this change, on the same terms as `start`. Null when "
            + "Microsoft 365 gave no end."
        )
    )
    attendee_ids: list[str] | None = Field(
        description=(
            "The Microsoft Entra object ids of the attendees that Microsoft 365 holds after this "
            + "change. The organizer is not in this list. Null when the answer of Microsoft 365 "
            + "held no attendee list."
        )
    )


@dataclass(frozen=True, slots=True)
class _Change:
    subject: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    attendees: tuple[str, ...] | None


async def update_meeting(
    client: GraphServiceClient,
    *,
    meeting_uri: str,
    subject: str | None = None,
    starts_at: str | None = None,
    ends_at: str | None = None,
    attendees: Sequence[str] | None = None,
    confirm: Confirm,
) -> UpdatedMeeting | InputRequiredResult:
    handle = meeting_handle(meeting_uri)
    if handle is None:
        raise ToolError(_NOT_A_MEETING_HANDLE)
    change = _change(subject, starts_at, ends_at, attendees)

    updated: OnlineMeeting | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        meeting = await resolve_meeting(client, handle)
        if meeting is None or meeting.id is None:
            refused = _NO_SUCH_MEETING
        elif not organized_by(meeting, await identity.signed_in_user(client)):
            refused = _NOT_THE_ORGANIZER
        else:
            with not_graph():
                answer = await confirm(_question(meeting, change), _about(handle, change))
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
            if refused is None and asked is None:
                with graph_step(STEP_UPDATE):
                    updated = await client.me.online_meetings.by_online_meeting_id(
                        meeting.id
                    ).patch(
                        _body(change),
                        request_configuration=RequestConfiguration[QueryParameters](
                            options=no_retry()
                        ),
                    )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert updated is not None, "Graph answered an online meeting PATCH with no meeting"
    return _answer(handle, updated)


def _change(
    subject: str | None,
    starts_at: str | None,
    ends_at: str | None,
    attendees: Sequence[str] | None,
) -> _Change:
    if subject is None and starts_at is None and ends_at is None and attendees is None:
        raise ToolError(_NOTHING_TO_CHANGE)
    if (starts_at is None) != (ends_at is None):
        raise ToolError(_ONE_TIME_ONLY)
    opens = None if starts_at is None else _instant("starts_at", starts_at)
    closes = None if ends_at is None else _instant("ends_at", ends_at)
    if opens is not None and closes is not None and closes <= opens:
        raise ToolError(_ENDS_BEFORE_IT_STARTS)
    return _Change(
        subject=subject,
        starts_at=opens,
        ends_at=closes,
        attendees=None
        if attendees is None
        else tuple(sorted({attendee.lower() for attendee in attendees})),
    )


def _instant(argument: str, value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise ToolError(_not_a_time(argument, value)) from None
    if moment.utcoffset() is None:
        raise ToolError(_no_offset(argument, value))
    return moment


def _utc(moment: datetime | None) -> datetime | None:
    return None if moment is None else moment.astimezone(UTC)


def _about(handle: MeetingHandle, change: _Change) -> str:
    starts_at = _utc(change.starts_at)
    ends_at = _utc(change.ends_at)
    return hashlib.sha256(
        json.dumps(
            [
                handle.uri,
                change.subject,
                None if starts_at is None else starts_at.isoformat(),
                None if ends_at is None else ends_at.isoformat(),
                None if change.attendees is None else list(change.attendees),
            ]
        ).encode()
    ).hexdigest()


def _question(meeting: OnlineMeeting, change: _Change) -> str:
    changes: list[str] = []
    if change.subject is not None:
        changes.append(f"the subject to {cut_for_a_question(change.subject)!r}")
    if change.starts_at is not None and change.ends_at is not None:
        changes.append(
            f"the time to {change.starts_at.isoformat()} until {change.ends_at.isoformat()}"
        )
    if change.attendees is not None:
        changes.append(
            f"the attendee list to {counted_people(change.attendees)}: "
            + ", ".join(change.attendees)
            if change.attendees
            else "the attendee list to nobody"
        )
    name = repr(cut_for_a_question(meeting.subject)) if meeting.subject else "that has no subject"
    left_out = f" {_LEFT_OUT}" if change.attendees is not None else ""
    return f"Change the Teams meeting {name}: {' and '.join(changes)}?{left_out}"


def _body(change: _Change) -> OnlineMeeting:
    return OnlineMeeting(
        subject=change.subject,
        start_date_time=_utc(change.starts_at),
        end_date_time=_utc(change.ends_at),
        participants=None
        if change.attendees is None
        else MeetingParticipants(
            attendees=[
                MeetingParticipantInfo(identity=IdentitySet(user=Identity(id=attendee)))
                for attendee in change.attendees
            ]
        ),
    )


def _answer(handle: MeetingHandle, updated: OnlineMeeting) -> UpdatedMeeting:
    participants = updated.participants
    attendees = None if participants is None else participants.attendees
    return UpdatedMeeting(
        meeting_uri=handle.uri,
        subject=updated.subject,
        start=updated.start_date_time,
        end=updated.end_date_time,
        attendee_ids=None
        if attendees is None
        else [
            attendee.identity.user.id
            for attendee in attendees
            if attendee.identity is not None
            and attendee.identity.user is not None
            and attendee.identity.user.id is not None
        ],
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_CHANGED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Update a Teams Meeting",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def teams_update_meeting(
        meeting_uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The meeting to change, as the `meeting_uri` handle from teams_list_chats: "
                    + "`teams:///meetings/{join_web_url}`. Copy it word for word. A "
                    + "`teams:///transcripts/...` handle is not valid here."
                ),
            ),
        ],
        ctx: Context,
        subject: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The new subject of the meeting, as the user writes it. This tool sends it to "
                    + "Microsoft 365 verbatim. Omit it to keep the current subject."
                ),
            ),
        ] = None,
        starts_at: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The new start of the meeting, as an ISO-8601 date and time with an offset or "
                    + "`Z`, for example `2026-03-02T14:00:00+01:00`. Give `ends_at` with it. Omit "
                    + "both to keep the current time."
                ),
            ),
        ] = None,
        ends_at: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The new end of the meeting, in the same form as `starts_at`, and after it. A "
                    + "meeting that runs past midnight ends on the next day."
                ),
            ),
        ] = None,
        attendees: Annotated[
            list[Annotated[str, Field(pattern=identity.ENTRA_OBJECT_ID_PATTERN)]] | None,
            Field(
                description=(
                    "The full new attendee list, as the Microsoft Entra object id of each person. "
                    + "This list replaces the current attendee list. Copy each id from the "
                    + "`user_id` of get_me, of a teams_list_chats member, or of a "
                    + "teams_list_chat_members row. Never build an id from a name or an email "
                    + "address. Omit it to keep the current attendees."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> UpdatedMeeting | InputRequiredResult:
        return await update_meeting(
            client,
            meeting_uri=meeting_uri,
            subject=subject,
            starts_at=starts_at,
            ends_at=ends_at,
            attendees=attendees,
            confirm=a_person_agrees(ctx),
        )
