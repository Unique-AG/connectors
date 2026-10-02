import json
import uuid
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
from msgraph.generated.models.online_meeting import OnlineMeeting
from msgraph.generated.users.item.online_meetings.create_or_get import (
    create_or_get_post_request_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, no_retry, not_graph
from office_365_mcp.shared.handles import meeting_uri_for
from office_365_mcp.shared.identity import Person
from office_365_mcp.shared.meetings import (
    attendee_ids,
    distinct_people,
    meeting_participants,
    meeting_times,
    named_people,
)
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_create_meeting"

STEP = "create_meeting"

GRAPH_PERMISSIONS: tuple[str, ...] = ("OnlineMeetings.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "subject": "Pricing review",
    "starts_at": "2026-03-02T14:00:00Z",
    "ends_at": "2026-03-02T15:00:00Z",
    "attendees": [{"user_id": "00000000-0000-4000-8000-000000000002", "name": "Grace Hopper"}],
}

_EXTERNAL_ID_NAMESPACE = uuid.UUID("e0f61b25-5f82-4ac9-846f-8df11567971a")

_CREATE = "create"
_DO_NOT_CREATE = "do not create"
_NOTHING_CREATED = "No meeting was created."
_FAILS_THE_SAME_WAY = (
    "If you call this tool again with the same arguments, the call will fail the same way."
)
_REFUSED = f"{_NOTHING_CREATED} {_FAILS_THE_SAME_WAY}"

_DESCRIPTION = """\
Creates one Teams online meeting as the signed-in user, with the attendees that the user names. \
The meeting is standalone. It is on no calendar, and this tool sends no invitation. To share the \
meeting, use the `join_web_url` of the answer. teams_read_meeting reads the meeting later.

Notes:
- This tool asks the user to agree before it creates anything, every time. This tool creates \
nothing unless the user agrees.
- Microsoft documents a calendar event with an online meeting as the way to read the transcript of \
a meeting later. If the user will want a transcript or a calendar event, tell the user this before \
you create the meeting.
- This call is safe to repeat after a timeout. The same request returns the same meeting, and it \
creates no second meeting.
"""


class CreatedMeeting(BaseModel):
    meeting_uri: str | None = Field(
        description=(
            "This is a handle for the meeting, built from its join URL. Pass this handle "
            + "verbatim to a tool that takes a `meeting_uri`. This field is null when Graph "
            + "returned no join URL."
        )
    )
    join_web_url: str | None = Field(
        description=(
            "This is the join URL of the meeting in Teams, exactly as Microsoft returned it. "
            + "Give this URL to the user. Share it only with the people that the user names. "
            + "This field is null when Graph returned none."
        )
    )
    subject: str | None = Field(
        description=(
            "This is the subject as Microsoft stored it, read from the response and not from "
            + "the arguments. This field is null when Graph recorded none."
        )
    )
    start: datetime | None = Field(
        description=(
            "This is when the meeting starts, in UTC, as Microsoft stored it. Report this time to "
            + "the user in the zone of the user. This field is null when Graph stated no start."
        )
    )
    end: datetime | None = Field(
        description=(
            "This is when the meeting ends, on the same terms as `start`. This field is null "
            + "when Graph stated no end."
        )
    )
    attendee_ids: list[str] = Field(
        description=(
            "These are the Microsoft Entra object ids of the attendees as Microsoft stored them, "
            + "read from the response and not from the arguments. This list does not include the "
            + "organizer. An empty list means that the meeting has no attendee."
        )
    )


@dataclass(frozen=True, slots=True)
class _Draft:
    subject: str
    starts_at: datetime
    ends_at: datetime
    attendees: tuple[Person, ...]


async def create_meeting(
    client: GraphServiceClient,
    *,
    subject: str,
    starts_at: str,
    ends_at: str,
    attendees: Sequence[Person],
    confirm: Confirm,
) -> CreatedMeeting | InputRequiredResult:
    draft = _drafted(subject, starts_at, ends_at, attendees)
    external_id = _external_id(draft)
    created: OnlineMeeting | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME, step=STEP):
        with not_graph():
            answer = await confirm(_question(draft), external_id)
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            created = await client.me.online_meetings.create_or_get.post(
                _body(draft, external_id=external_id),
                request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
            )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return _answer(created)


def _drafted(subject: str, starts_at: str, ends_at: str, attendees: Sequence[Person]) -> _Draft:
    times = meeting_times(TOOL_NAME, starts_at, ends_at, tail=_REFUSED)
    if isinstance(times, str):
        raise ToolError(times)
    opens, closes = times
    return _Draft(
        subject=subject,
        starts_at=opens,
        ends_at=closes,
        attendees=distinct_people(attendees),
    )


def _external_id(draft: _Draft) -> str:
    canonical = json.dumps(
        [
            draft.subject,
            draft.starts_at.astimezone(UTC).isoformat(),
            draft.ends_at.astimezone(UTC).isoformat(),
            [attendee.user_id for attendee in draft.attendees],
        ]
    )
    return str(uuid.uuid5(_EXTERNAL_ID_NAMESPACE, canonical))


def _question(draft: _Draft) -> str:
    attendees = named_people(draft.attendees) if draft.attendees else "no attendee"
    return (
        f"Create the Teams meeting {cut_for_a_question(draft.subject)!r} from "
        + f"{draft.starts_at.isoformat()} to {draft.ends_at.isoformat()} with {attendees}? The "
        + "meeting is on no calendar, and this tool sends no invitation."
    )


def _body(
    draft: _Draft, *, external_id: str
) -> create_or_get_post_request_body.CreateOrGetPostRequestBody:
    return create_or_get_post_request_body.CreateOrGetPostRequestBody(
        external_id=external_id,
        subject=draft.subject,
        start_date_time=draft.starts_at.astimezone(UTC),
        end_date_time=draft.ends_at.astimezone(UTC),
        participants=meeting_participants([attendee.user_id for attendee in draft.attendees]),
    )


def _answer(created: OnlineMeeting | None) -> CreatedMeeting:
    assert created is not None, "Graph answered createOrGet with no meeting"
    return CreatedMeeting(
        meeting_uri=meeting_uri_for(created.join_web_url),
        join_web_url=created.join_web_url,
        subject=created.subject,
        start=created.start_date_time,
        end=created.end_date_time,
        attendee_ids=attendee_ids(created.participants) or [],
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Teams Meeting",
        description=_DESCRIPTION,
        annotations=WRITE_IDEMPOTENT,
    )
    async def teams_create_meeting(
        subject: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "This is the subject of the meeting, as the user writes it. This tool sends "
                    + "the subject to Microsoft verbatim."
                ),
            ),
        ],
        starts_at: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "This is when the meeting starts, as an ISO-8601 date and time with an "
                    + "offset or `Z`, for example `2026-03-02T14:00:00+01:00`. This tool refuses "
                    + "a time with no offset. If the zone, the day, or the hour is ambiguous, ask "
                    + "the user instead of a guess."
                ),
            ),
        ],
        ends_at: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "This is when the meeting ends, in the same form as `starts_at`, and after "
                    + "it. A meeting that runs past midnight ends on the next day."
                ),
            ),
        ],
        attendees: Annotated[
            list[Person],
            Field(
                description=(
                    "These are the people to add as attendees, with one entry for each person. "
                    + "Pass an empty list for a meeting with no attendee."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> CreatedMeeting | InputRequiredResult:
        return await create_meeting(
            client,
            subject=subject,
            starts_at=starts_at,
            ends_at=ends_at,
            attendees=attendees,
            confirm=a_person_agrees(ctx),
        )
