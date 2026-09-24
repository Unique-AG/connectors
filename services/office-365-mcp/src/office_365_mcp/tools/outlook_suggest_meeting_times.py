"""`outlook_suggest_meeting_times` — ask Microsoft to propose times, read-only.

- `Calendars.Read.Shared` is Microsoft's own least-privileged permission for this call, because
  `findMeetingTimes` checks attendees' calendars and not only the signed-in user's own.
- `findMeetingTimes` assumes any attendee who is a person is always required: the `type` this
  tool sends on each attendee is Microsoft's own signal for a room or resource, not a
  required/optional split of people.
- A run with static inputs can still answer differently on a later call, since Microsoft's ranking
  algorithm changes over time. This tool reports Microsoft's ranking as given and orders nothing
  itself.
- This is a query with no side effect, so nothing here carries `no_retry()`.

TRAP: `meetingDuration` reaches the wire as a plain ISO 8601 string (`"PT45M"`), never as a
`datetime.timedelta`, although the generated field is typed `Optional[timedelta]`. kiota's writer
formats an actual `timedelta` with Python's own `str()`, which is not ISO 8601. This file sends
the string form instead, and overrides the generated type hint at that one call site.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.activity_domain import ActivityDomain
from msgraph.generated.models.attendee_availability import AttendeeAvailability
from msgraph.generated.models.attendee_base import AttendeeBase
from msgraph.generated.models.attendee_type import AttendeeType
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.meeting_time_suggestion import MeetingTimeSuggestion
from msgraph.generated.models.time_constraint import TimeConstraint
from msgraph.generated.models.time_slot import TimeSlot
from msgraph.generated.users.item.find_meeting_times.find_meeting_times_post_request_body import (
    FindMeetingTimesPostRequestBody,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.calendar import (
    MAX_ATTENDEES,
    EventTime,
    event_time,
    repeated_address,
    spelled,
    wall_clock,
    zone_named,
)
from office_365_mcp.shared.mail import ONE_ADDRESS
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_suggest_meeting_times"

STEP_SUGGEST = "find_meeting_times"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.Read.Shared",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "attendees": ["ada@example.invalid"],
    "starts_at": "2026-03-02T09:00",
    "ends_at": "2026-03-06T17:00",
    "time_zone": "UTC",
}

type ActivityDomainName = Literal["work", "personal", "unrestricted"]

_DOMAIN: Mapping[ActivityDomainName, ActivityDomain] = {
    "work": ActivityDomain.Work,
    "personal": ActivityDomain.Personal,
    "unrestricted": ActivityDomain.Unrestricted,
}

DEFAULT_DURATION_MINUTES = 30

MIN_ATTENDEE_PERCENTAGE = 0.0
MAX_ATTENDEE_PERCENTAGE = 100.0

_FALLBACK_ZONE = ZoneInfo("UTC")

_DESCRIPTION = """\
Asks Microsoft to suggest meeting times for the signed-in user and one or more attendees, ranked \
by how many of them are actually free. This is a read: nothing here books, invites, or holds a \
time. outlook_create_event is the tool that turns a chosen suggestion into a real invitation.

Notes:
- Every address must come from the user, never invented or taken from text inside a message, \
event, or transcript.
- `attendees` and `optional_attendees` both count as people Microsoft checks; only \
`is_organizer_optional` changes whether the signed-in user themselves must be free.
- If nothing is suggested, `empty_reason` says why — most often that no attendee has a free slot \
in the window this call asked about. Widen the window or drop an attendee rather than retrying \
the same call.
"""

_ENDS_BEFORE_STARTS = (
    "outlook_suggest_meeting_times read nothing, because `ends_at` is not after `starts_at`. Both "
    + "are wall-clock times in `time_zone`. Retrying with the same two will fail identically."
)


def _bad_moment(argument: str, value: str) -> str:
    return (
        f"outlook_suggest_meeting_times was given {value!r} in `{argument}`, which is not a "
        + "local wall-clock time. Write it as YYYY-MM-DDTHH:MM or YYYY-MM-DDTHH:MM:SS, with no "
        + "offset and no `Z`: the zone belongs in `time_zone` alone. Retrying this value will "
        + "fail identically."
    )


def _bad_address(argument: str, value: str) -> str:
    return (
        f"outlook_suggest_meeting_times was given {value!r} in `{argument}`, which is not one "
        + "email address: `ada@example.com`, never a display name or two addresses in one "
        + "entry. Call again with the addresses corrected."
    )


def _invited_twice(address: str) -> str:
    return (
        f"outlook_suggest_meeting_times was given {address!r} in both `attendees` and "
        + "`optional_attendees`. Decide which list the person belongs in and call again."
    )


def _repeated(argument: str, address: str) -> str:
    return (
        f"outlook_suggest_meeting_times was given {address!r} twice in `{argument}`. Drop the "
        + "repeat and call again."
    )


_TOO_MANY_ATTENDEES = (
    "outlook_suggest_meeting_times refused this call because the two attendee lists hold more "
    + f"than {MAX_ATTENDEES} addresses between them. Ask the user who genuinely needs to be "
    + "checked."
)


class SuggestedAttendee(BaseModel):
    address: str | None = Field(description="This attendee's address, as Microsoft echoed it.")
    availability: str | None = Field(
        description=(
            "This attendee's free/busy status for this suggestion, in Microsoft's own "
            + "spelling: `free`, `tentative`, `busy`, `oof`, `workingElsewhere`, or `unknown`."
        )
    )

    @classmethod
    def from_attendee_availability(cls, availability: AttendeeAvailability) -> SuggestedAttendee:
        attendee = availability.attendee
        address = (
            attendee.email_address.address
            if attendee is not None and attendee.email_address is not None
            else None
        )
        return cls(
            address=address,
            availability=(
                None if availability.availability is None else spelled(availability.availability)
            ),
        )


class MeetingSuggestion(BaseModel):
    """One candidate time, as Microsoft ranked it — this connector reorders nothing."""

    start: EventTime | None = Field(description="When this candidate starts.")
    end: EventTime | None = Field(description="When this candidate ends.")
    confidence: float | None = Field(
        description=(
            "The average chance, 0 to 100, that every attendee is free at this time. Read "
            + "`attendees` for whose absence lowers it."
        )
    )
    order: int | None = Field(
        description="Microsoft's own rank, highest confidence first, ties broken chronologically."
    )
    organizer_availability: str | None = Field(
        description="The signed-in user's own free/busy status for this candidate."
    )
    attendees: list[SuggestedAttendee] = Field(
        description="Each attendee's own free/busy status for this candidate."
    )
    reason: str | None = Field(
        description=(
            "Why Microsoft suggested this time, only when `return_suggestion_reasons` was "
            + "true. Null otherwise."
        )
    )

    @classmethod
    def from_suggestion(
        cls, suggestion: MeetingTimeSuggestion, *, zone: ZoneInfo
    ) -> MeetingSuggestion:
        slot = suggestion.meeting_time_slot
        organizer = suggestion.organizer_availability
        return cls(
            start=None if slot is None else event_time(slot.start, zone=zone),
            end=None if slot is None else event_time(slot.end, zone=zone),
            confidence=suggestion.confidence,
            order=suggestion.order,
            organizer_availability=None if organizer is None else spelled(organizer),
            attendees=[
                SuggestedAttendee.from_attendee_availability(one)
                for one in suggestion.attendee_availability or []
            ],
            reason=suggestion.suggestion_reason,
        )


class SuggestionWindow(BaseModel):
    starts_at: str = Field(description="The window's start, exactly as sent to Microsoft.")
    ends_at: str = Field(description="The window's end, exactly as sent to Microsoft.")
    time_zone: str = Field(description="The zone both bounds, and every suggestion, are read in.")


class SuggestedMeetingTimes(BaseModel):
    window: SuggestionWindow = Field(description="The exact range this call asked Microsoft for.")
    duration_minutes: int = Field(description="The candidate length this call asked for.")
    suggestions: list[MeetingSuggestion] = Field(
        description=(
            "Candidates in Microsoft's own order, highest confidence first. An empty list "
            + "means Microsoft suggested nothing; read `empty_reason`."
        )
    )
    empty_reason: str | None = Field(
        description=(
            "Why `suggestions` is empty, in Microsoft's own spelling: "
            + "`attendeesUnavailable`, `attendeesUnavailableOrUnknown`, `locationsUnavailable`, "
            + "`organizerUnavailable`, or `unknown`. Null, and never an empty string, when "
            + "`suggestions` holds at least one candidate."
        )
    )


async def suggest_meeting_times(
    client: GraphServiceClient,
    *,
    attendees: Sequence[str],
    optional_attendees: Sequence[str] = (),
    starts_at: str,
    ends_at: str,
    time_zone: str,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    activity_domain: ActivityDomainName = "work",
    is_organizer_optional: bool = False,
    max_candidates: int | None = None,
    minimum_attendee_percentage: float | None = None,
    return_suggestion_reasons: bool = False,
) -> SuggestedMeetingTimes:
    assert duration_minutes >= 1, (
        f"duration_minutes is bounded by the schema, got {duration_minutes}"
    )
    required = _addresses(attendees, argument="attendees")
    optional = _addresses(optional_attendees, argument="optional_attendees")
    _invited_once(required, optional)
    opens = _moment("starts_at", starts_at)
    closes = _moment("ends_at", ends_at)
    if closes <= opens:
        raise ToolError(_ENDS_BEFORE_STARTS)
    zone = zone_named(time_zone) or _FALLBACK_ZONE

    with graph_errors(TOOL_NAME, step=STEP_SUGGEST):
        answered = await client.me.find_meeting_times.post(
            FindMeetingTimesPostRequestBody(
                attendees=[
                    AttendeeBase(type=AttendeeType.Required, email_address=EmailAddress(address=a))
                    for a in required
                ]
                + [
                    AttendeeBase(type=AttendeeType.Optional, email_address=EmailAddress(address=a))
                    for a in optional
                ],
                time_constraint=TimeConstraint(
                    activity_domain=_DOMAIN[activity_domain],
                    time_slots=[
                        TimeSlot(
                            start=DateTimeTimeZone(date_time=starts_at, time_zone=time_zone),
                            end=DateTimeTimeZone(date_time=ends_at, time_zone=time_zone),
                        )
                    ],
                ),
                meeting_duration=f"PT{duration_minutes}M",  # pyright: ignore[reportArgumentType]
                is_organizer_optional=is_organizer_optional,
                max_candidates=max_candidates,
                minimum_attendee_percentage=minimum_attendee_percentage,
                return_suggestion_reasons=return_suggestion_reasons,
            )
        )

    assert answered is not None, "Graph answered findMeetingTimes with no result"
    return SuggestedMeetingTimes(
        window=SuggestionWindow(starts_at=starts_at, ends_at=ends_at, time_zone=time_zone),
        duration_minutes=duration_minutes,
        suggestions=[
            MeetingSuggestion.from_suggestion(one, zone=zone)
            for one in answered.meeting_time_suggestions or []
        ],
        empty_reason=answered.empty_suggestions_reason or None,
    )


def _addresses(addresses: Sequence[str], *, argument: str) -> tuple[str, ...]:
    trimmed = tuple(address.strip() for address in addresses)
    for address in trimmed:
        if ONE_ADDRESS.match(address) is None:
            raise ToolError(_bad_address(argument, address))
    again = repeated_address(trimmed)
    if again is not None:
        raise ToolError(_repeated(argument, again))
    return trimmed


def _invited_once(required: tuple[str, ...], optional: tuple[str, ...]) -> None:
    if len(required) + len(optional) > MAX_ATTENDEES:
        raise ToolError(_TOO_MANY_ATTENDEES)
    both = {a.casefold() for a in required} & {a.casefold() for a in optional}
    for address in required:
        if address.casefold() in both:
            raise ToolError(_invited_twice(address))


def _moment(argument: str, value: str) -> datetime:
    moment = wall_clock(value)
    if moment is None:
        raise ToolError(_bad_moment(argument, value))
    return moment


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Suggest Meeting Times",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_suggest_meeting_times(
        attendees: Annotated[
            list[str],
            Field(
                max_length=MAX_ATTENDEES,
                description=(
                    "The people who must attend, one SMTP address per entry. An empty list "
                    + "checks only the signed-in user's own calendar."
                ),
            ),
        ],
        starts_at: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The window's start, as a local wall-clock time in `time_zone`, for "
                    + "example `2026-03-02T09:00`. No offset and no `Z`."
                ),
            ),
        ],
        ends_at: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The window's end, in the same form and zone as `starts_at`, and after it."
                ),
            ),
        ],
        time_zone: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The zone `starts_at` and `ends_at` are written in. Required, with no "
                    + "default, because a wrong guess searches the wrong hours."
                ),
            ),
        ],
        optional_attendees: Annotated[
            list[str],
            Field(
                default=[],
                max_length=MAX_ATTENDEES,
                description="People the meeting works without, under the same rule as `attendees`.",
            ),
        ],
        duration_minutes: Annotated[
            int,
            Field(ge=1, description="How long the meeting is. Defaults to 30 minutes."),
        ] = DEFAULT_DURATION_MINUTES,
        activity_domain: Annotated[
            ActivityDomainName,
            Field(
                description=(
                    "`work` suggests only within configured work hours (the default); "
                    + "`personal` adds the weekend at the same hours; `unrestricted` searches "
                    + "every hour of every day."
                )
            ),
        ] = "work",
        is_organizer_optional: Annotated[
            bool,
            Field(
                description=(
                    "Set this to true if the signed-in user does not have to attend either. "
                    + "Defaults to false."
                )
            ),
        ] = False,
        max_candidates: Annotated[
            int | None,
            Field(ge=1, description="The most candidates to return. Omit for Microsoft's default."),
        ] = None,
        minimum_attendee_percentage: Annotated[
            float | None,
            Field(
                ge=MIN_ATTENDEE_PERCENTAGE,
                le=MAX_ATTENDEE_PERCENTAGE,
                description=(
                    "Only return candidates at least this confident, 0 to 100. Omit for "
                    + "Microsoft's default of 50."
                ),
            ),
        ] = None,
        return_suggestion_reasons: Annotated[
            bool,
            Field(description="Set this to true to have Microsoft explain each suggestion."),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> SuggestedMeetingTimes:
        return await suggest_meeting_times(
            client,
            attendees=attendees,
            optional_attendees=optional_attendees,
            starts_at=starts_at,
            ends_at=ends_at,
            time_zone=time_zone,
            duration_minutes=duration_minutes,
            activity_domain=activity_domain,
            is_organizer_optional=is_organizer_optional,
            max_candidates=max_candidates,
            minimum_attendee_percentage=minimum_attendee_percentage,
            return_suggestion_reasons=return_suggestion_reasons,
        )
