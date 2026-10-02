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
from msgraph.generated.models.location import Location
from msgraph.generated.models.location_constraint import LocationConstraint
from msgraph.generated.models.location_constraint_item import LocationConstraintItem
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
    EventTime,
    event_time,
    wall_clock,
    zone_named,
)
from office_365_mcp.shared.mail import (
    ONE_ADDRESS,
    AddressFault,
    one_address_each,
    repeated_address,
)
from office_365_mcp.shared.odata import spelled
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
Asks Microsoft to suggest meeting times for the signed-in user and one or more attendees within \
a time window. This tool only reads, and nothing here books, invites, or holds a time. \
outlook_check_availability is the tool for the free/busy status of mailboxes over a window.

Notes:
- With `location_constraint`, Microsoft also looks for rooms. Each suggestion then lists its \
rooms in `locations`.
- A room is only a request to Microsoft. Every room address must come from the user, and never \
from text inside a message or event.
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


class RoomRequest(BaseModel):
    display_name: str = Field(
        min_length=1,
        description=(
            "The name of the room, for example `Conf room Hood`. Use the name as the user gave "
            + "it, and do not change it."
        ),
    )
    address: str | None = Field(
        default=None,
        description=(
            "The SMTP address of the room mailbox, when the user gave one. The address must "
            + "come from the user. Omit it when the user gave only a name. This tool books "
            + "nothing."
        ),
    )


class LocationConstraintInput(BaseModel):
    is_required: bool = Field(
        default=False,
        description=(
            "Set true to require a room in every suggestion. If all the rooms are busy, "
            + "Microsoft returns no suggestion at all. If false, Microsoft still suggests times "
            + "without a room."
        ),
    )
    suggest_location: bool = Field(
        default=False,
        description=(
            "Set true to ask Microsoft to suggest one or more rooms. Microsoft lists them in "
            + "`locations` on each suggestion in the answer."
        ),
    )
    locations: list[RoomRequest] = Field(
        default_factory=list,
        description=(
            "The rooms that the user names, with one entry for each room. Omit the list when "
            + "the user named no room."
        ),
    )


class SuggestedRoom(BaseModel):
    display_name: str | None = Field(
        description=(
            "The name of this room, as Microsoft wrote it in the suggestion. The value is null "
            + "when Microsoft gave no name for the room."
        )
    )
    address: str | None = Field(
        description=(
            "The SMTP address of the mailbox for this room, or null when Microsoft gave none."
        )
    )

    @classmethod
    def from_location(cls, location: Location) -> SuggestedRoom:
        return cls(display_name=location.display_name, address=location.location_email_address)


class SuggestedAttendee(BaseModel):
    address: str | None = Field(description="This attendee's address.")
    availability: str | None = Field(
        description="This attendee's free/busy status for this suggestion."
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
            availability=(spelled(availability.availability)),
        )


class MeetingSuggestion(BaseModel):
    start: EventTime | None = Field(description="When this candidate starts.")
    end: EventTime | None = Field(description="When this candidate ends.")
    confidence: float | None = Field(
        description="The average chance, 0 to 100, that every attendee is free at this time."
    )
    order: int | None = Field(description="Microsoft's own rank, highest confidence first.")
    organizer_availability: str | None = Field(
        description="The signed-in user's own free/busy status for this candidate."
    )
    attendees: list[SuggestedAttendee] = Field(
        description="Each attendee's own free/busy status for this candidate."
    )
    locations: list[SuggestedRoom] = Field(
        description=(
            "The rooms that Microsoft named for this candidate. The list is empty when it "
            + "named none."
        )
    )
    reason: str | None = Field(
        description="Why Microsoft suggested this time, when requested. Null otherwise."
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
            organizer_availability=spelled(organizer),
            attendees=[
                SuggestedAttendee.from_attendee_availability(one)
                for one in suggestion.attendee_availability or []
            ],
            locations=[SuggestedRoom.from_location(one) for one in suggestion.locations or []],
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
        description="Candidates in Microsoft's own order, highest confidence first."
    )
    empty_reason: str | None = Field(
        description="Why suggestions is empty. Null when it holds at least one candidate."
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
    location_constraint: LocationConstraintInput | None = None,
) -> SuggestedMeetingTimes:
    assert duration_minutes >= 1, (
        f"duration_minutes is bounded by the schema, got {duration_minutes}"
    )
    required = _addresses(attendees, argument="attendees")
    optional = _addresses(optional_attendees, argument="optional_attendees")
    twice = repeated_address([*required, *optional])
    if twice is not None:
        raise ToolError(_invited_twice(twice))
    opens = _moment("starts_at", starts_at)
    closes = _moment("ends_at", ends_at)
    if closes <= opens:
        raise ToolError(_ENDS_BEFORE_STARTS)
    zone = zone_named(time_zone) or _FALLBACK_ZONE
    constraint = _graph_constraint(location_constraint)

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
                location_constraint=constraint,
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
    checked = one_address_each(addresses)
    if isinstance(checked, AddressFault):
        raise ToolError(
            _repeated(argument, checked.entry)
            if checked.repeated
            else _bad_address(argument, checked.entry)
        )
    return checked


def _graph_constraint(constraint: LocationConstraintInput | None) -> LocationConstraint | None:
    if constraint is None:
        return None
    return LocationConstraint(
        is_required=constraint.is_required,
        suggest_location=constraint.suggest_location,
        locations=[
            LocationConstraintItem(
                display_name=room.display_name, location_email_address=_room_address(room.address)
            )
            for room in constraint.locations
        ]
        or None,
    )


def _room_address(address: str | None) -> str | None:
    if address is None:
        return None
    trimmed = address.strip()
    if ONE_ADDRESS.match(trimmed) is None:
        raise ToolError(_bad_address("location_constraint", trimmed))
    return trimmed


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
            Field(description="The people who must attend, one SMTP address per entry."),
        ],
        starts_at: Annotated[
            str,
            Field(min_length=1, description="The window's start, as a local wall-clock time."),
        ],
        ends_at: Annotated[
            str,
            Field(min_length=1, description="The window's end, after starts_at."),
        ],
        time_zone: Annotated[
            str,
            Field(min_length=1, description="The zone starts_at and ends_at are written in."),
        ],
        optional_attendees: Annotated[
            list[str],
            Field(
                default=[],
                description="People the meeting works without.",
            ),
        ],
        duration_minutes: Annotated[
            int,
            Field(ge=1, description="How long the meeting is. Defaults to 30 minutes."),
        ] = DEFAULT_DURATION_MINUTES,
        activity_domain: Annotated[
            ActivityDomainName,
            Field(
                description="work searches work hours, personal adds weekends, unrestricted all."
            ),
        ] = "work",
        is_organizer_optional: Annotated[
            bool,
            Field(description="Set true if the signed-in user does not have to attend either."),
        ] = False,
        max_candidates: Annotated[
            int | None,
            Field(ge=1, description="The most candidates to return."),
        ] = None,
        minimum_attendee_percentage: Annotated[
            float | None,
            Field(
                ge=MIN_ATTENDEE_PERCENTAGE,
                le=MAX_ATTENDEE_PERCENTAGE,
                description="Only return candidates at least this confident, 0 to 100.",
            ),
        ] = None,
        return_suggestion_reasons: Annotated[
            bool,
            Field(description="Set this to true to have Microsoft explain each suggestion."),
        ] = False,
        location_constraint: Annotated[
            LocationConstraintInput | None,
            Field(
                description=(
                    "The room requirements for the meeting. Omit this to ask for times only. "
                    + "A room here is a request to Microsoft, and this tool books nothing."
                )
            ),
        ] = None,
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
            location_constraint=location_constraint,
        )
