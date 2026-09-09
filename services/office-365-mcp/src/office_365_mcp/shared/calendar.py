"""What an Outlook calendar and an Outlook event are: the shapes every calendar tool answers in.

- Graph states an instant as a `dateTime` with no offset plus a separate `timeZone` name, and with
  no `Prefer: outlook.timezone` header both come back in UTC
  (https://learn.microsoft.com/en-us/graph/api/user-list-calendarview). No tool here sends it.
- `timeZone` is often a Windows name such as `W. Europe Standard Time`, which `zoneinfo` cannot
  resolve, so `EventTime.iso` is null for those; on an all-day event both bounds are UTC midnight,
  so `local` and not `iso` names the day it covers.
- A create is a send: "the server sends invitations to all attendees", and that "can't be
  configured" (https://learn.microsoft.com/en-us/graph/api/user-post-events). `transactionId` is
  the only defense against a duplicated one, and Microsoft documents no comparison rule for it.
"""

import html
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.attendee import Attendee
from msgraph.generated.models.attendee_type import AttendeeType
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.calendar import Calendar
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.event import Event
from msgraph.generated.models.event_type import EventType
from msgraph.generated.models.free_busy_status import FreeBusyStatus
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.location import Location
from msgraph.generated.models.online_meeting_provider_type import OnlineMeetingProviderType
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.response_type import ResponseType
from msgraph.generated.models.sensitivity import Sensitivity
from msgraph.generated.models.user import User
from msgraph.generated.users.item.calendar.calendar_request_builder import CalendarRequestBuilder
from msgraph.generated.users.item.calendars.item.calendar_item_request_builder import (
    CalendarItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_step
from office_365_mcp.shared.handles import CalendarHandle, EventHandle
from office_365_mcp.shared.mail import MailAddress

STEP_CALENDAR = "calendar"

# Graph publishes no `isSharedWithMe` on `calendar` in v1.0, so `owner` is what tells a delegated
# calendar from the user's own.
CALENDAR_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "owner",
    "canEdit",
    "canShare",
    "canViewPrivateItems",
    "isDefaultCalendar",
    "isTallyingResponses",
    "allowedOnlineMeetingProviders",
    "defaultOnlineMeetingProvider",
)

# Graph documents no `$filter` over attendees, so `attendees` is selected for a client-side person
# match. Microsoft warns that a large page with no `$select` risks a gateway timeout.
SUMMARY_FIELDS: tuple[str, ...] = (
    "id",
    "subject",
    "bodyPreview",
    "start",
    "end",
    "isAllDay",
    "isCancelled",
    "type",
    "seriesMasterId",
    "sensitivity",
    "showAs",
    "location",
    "isOnlineMeeting",
    "onlineMeeting",
    "organizer",
    "isOrganizer",
    "responseStatus",
    "attendees",
    "webLink",
)

# `calendarView` expands a recurring series into one row per occurrence, so a wide window is
# hundreds of rows of the same meeting.
MAX_WINDOW_DAYS = 92

# Graph's own cap is 500 (https://learn.microsoft.com/en-us/graph/api/resources/event); far lower
# here on purpose, because every address receives an invitation this connector cannot recall.
MAX_ATTENDEES = 20

MAX_SUBJECT_CHARACTERS = 255

MAX_LOCATION_CHARACTERS = 255

NOBODY_INVITED_BUT_A_PLACE = (
    "Nobody is invited, and a location that names a bookable room can reach that room's mailbox."
)

MAX_TIMED_EVENT_HOURS = 24
MAX_ALL_DAY_EVENT_DAYS = 14

# `datetime.fromisoformat` is not this check: since 3.11 it also reads `2026-03-02` and
# `2026-03-02T24:00` (the next day's midnight), and a create sends the caller's own string.
WALL_CLOCK = re.compile(r"\A\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\Z")

# Both name families Graph accepts fit these characters (`W. Europe Standard Time`, `Etc/GMT+2`),
# and the name reaches verbatim the question a person answers.
ZONE_NAME = r"^[A-Za-z0-9][A-Za-z0-9 _./+-]*$"

MAX_ZONE_CHARACTERS = 64

# What a real tag looks like, so a "<" followed by a space, a digit or a symbol stays as the text
# it is: `Budget < 5000 EUR` is a sentence and `<[^>]+>` deletes the rest of it without a marker.
_A_TAG = re.compile(r"<(?:!--.*?--|/?[A-Za-z][^<>]*)>", re.DOTALL)

# Script and style go with their contents: CSS filling the cut hides the words a recipient reads.
_A_HIDDEN_ELEMENT = re.compile(r"<(script|style)\b[^<>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE)

_PREVIEW_CHARACTERS = 120

# Aliases of the classes rather than `type` statements, because each one is also constructed.
_DefaultCalendarQuery = CalendarRequestBuilder.CalendarRequestBuilderGetQueryParameters
_NamedCalendarQuery = CalendarItemRequestBuilder.CalendarItemRequestBuilderGetQueryParameters

# Never change this: a new namespace makes every id already sent unrecognizable to Graph, which is
# the point of sending one.
_TRANSACTION_NAMESPACE = uuid.UUID("eb6f3437-0196-4593-b4d7-a6044db0acdf")

# Graph answers `responseStatus.time` with `0001-01-01T00:00:00Z` when nobody responded.
_UNANSWERED_YEAR = 1

# One tuple rather than two classes in the `except`: `ruff format` rewrites the parenthesized form
# into PEP 758's `except A, B:`, which an older interpreter reads as a syntax error.
_NO_SUCH_ZONE: tuple[type[Exception], ...] = (ZoneInfoNotFoundError, ValueError)

_AN_EVENT = "#microsoft.graph.event"


class EventTime(BaseModel):
    """One instant as Graph states it, plus the same instant as a comparable ISO-8601 value."""

    local: str = Field(
        description=(
            "The wall-clock time Microsoft holds for this event, exactly as Graph wrote it and "
            + "with no offset in it. Read it together with `time_zone`: on its own it says nothing "
            + "about which instant it is."
        )
    )
    time_zone: str | None = Field(
        description=(
            "The name of the zone `local` is stated in, exactly as Graph wrote it. It is either an "
            + "IANA name such as `Europe/Zurich` or a Windows name such as `W. Europe Standard "
            + "Time`, because Microsoft accepts and returns both. Null when Graph named none."
        )
    )
    iso: str | None = Field(
        description=(
            "The same instant as an ISO-8601 timestamp with an offset, in the zone that was asked "
            + "for. This value is the one to compare, to sort on and to quote. On an all-day "
            + "event it is a UTC midnight moved into this zone, so it names a time of day and "
            + "sometimes a neighboring date: read `local` for the date such a row covers. Null "
            + "when Graph named a zone that this connector cannot resolve, which happens for "
            + "Windows zone names: `local` and `time_zone` still say what Microsoft holds."
        )
    )


def zone_named(name: str) -> ZoneInfo | None:
    """`zoneinfo` raises `ValueError`, not `ZoneInfoNotFoundError`, for a key that is not a
    normalized relative path, such as an empty string."""
    try:
        return ZoneInfo(name)
    except _NO_SUCH_ZONE:
        return None


def event_time(moment: DateTimeTimeZone | None, *, zone: ZoneInfo) -> EventTime | None:
    """Graph writes `dateTime` with seven fractional digits (`2026-09-07T13:00:00.0000000`), which
    `datetime.fromisoformat` accepts, keeping the six it has room for."""
    if moment is None or moment.date_time is None:
        return None
    return EventTime(
        local=moment.date_time,
        time_zone=moment.time_zone,
        iso=_converted(moment.date_time, moment.time_zone, zone),
    )


def _converted(local: str, named: str | None, zone: ZoneInfo) -> str | None:
    stated = None if named is None else zone_named(named)
    if stated is None:
        return None
    try:
        naive = datetime.fromisoformat(local)
    except ValueError:
        return None
    return naive.replace(tzinfo=stated).astimezone(zone).isoformat(timespec="seconds")


def window_bounds(starts_on: date, ends_on: date, *, zone: ZoneInfo) -> tuple[str, str]:
    """Graph reads these bounds by the offset in the value and not the `Prefer` header
    (https://learn.microsoft.com/en-us/graph/api/user-list-calendarview)."""
    opens = datetime.combine(starts_on, time.min, tzinfo=zone)
    closes = datetime.combine(ends_on + timedelta(days=1), time.min, tzinfo=zone)
    return opens.isoformat(timespec="seconds"), closes.isoformat(timespec="seconds")


def wall_clock(value: str) -> datetime | None:
    """The parsed value is never sent: Graph reads `dateTime` beside `timeZone`, so reformatting
    the caller's string changes which instant the event is at."""
    if WALL_CLOCK.match(value) is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_midnight(moment: datetime) -> bool:
    """Whether `moment` is midnight, where Microsoft requires both bounds of an all-day event
    (https://learn.microsoft.com/en-us/graph/api/resources/event)."""
    return moment.time() == time.min


class CalendarSummary(BaseModel):
    """One calendar of the signed-in user's mailbox, own or delegated."""

    uri: str = Field(
        description=(
            "A handle for this exact calendar. Pass it verbatim wherever a tool takes a "
            + "`calendar_ref`. A calendar id stays the same for as long as the calendar exists, so "
            + "this handle does not expire on its own."
        )
    )
    name: str | None = Field(
        description=(
            "The calendar's name. A calendar that another person shared is named after that "
            + "person, not after a folder. Null when Graph recorded none."
        )
    )
    owner: MailAddress | None = Field(
        description=(
            "Whose calendar this is. On a delegated calendar this is the other person, and it is "
            + "the only property that says so. Null when Graph recorded no owner."
        )
    )
    is_mine: bool | None = Field(
        description=(
            "Whether the owner is the signed-in user, compared on the address without regard to "
            + "case. Null when this answer was composed without reading the signed-in user, or "
            + "when Graph recorded no owner: null means unknown and never false."
        )
    )
    can_edit: bool | None = Field(
        description=(
            "Whether the signed-in user can write to this calendar. False on a calendar shared "
            + "read-only, where a create fails whatever else is right about it."
        )
    )
    can_view_private_items: bool | None = Field(
        description=(
            "Whether the signed-in user sees the details of items the owner marked private. On "
            + "one calendar where this and `can_edit` were both false, every row arrived stripped "
            + "even though its `sensitivity` was `normal`: an empty `preview`, `attendee_count` "
            + "0, and `subject` holding the display form of its own `show_as` (`Tentative` for "
            + "`tentative`). The two flags alone do not say a row was stripped; on a calendar "
            + "with both false, a row of that shape does."
        )
    )
    is_default: bool | None = Field(
        description=(
            "Whether this is the mailbox's primary calendar, which is the one a create writes to "
            + "when no calendar is named."
        )
    )
    tracks_responses: bool | None = Field(
        description=(
            "Whether this calendar tallies the responses of the people invited to its events. "
            + "False on a calendar Outlook does not track, where an attendee's response never "
            + "reaches the row."
        )
    )
    online_meeting_providers: list[str] = Field(
        description=(
            "Which online-meeting providers this calendar accepts, in Microsoft's own spelling: "
            + "`teamsForBusiness`, `skypeForBusiness`, `skypeForConsumer` or `unknown`. Empty when "
            + "Graph named none, which is not proof that none works."
        )
    )
    default_online_meeting_provider: str | None = Field(
        description=(
            "The provider a new online meeting on this calendar uses, in Microsoft's own "
            + "spelling. Null when Graph named none."
        )
    )

    @classmethod
    def from_calendar(cls, calendar: Calendar, *, signed_in: User | None) -> Self:
        assert calendar.id is not None, "Graph answered a calendar read with a calendar with no id"
        owner = MailAddress.from_email_address(calendar.owner)
        # kiota deserializes a provider this SDK has no member for as None inside the list,
        # whatever the SDK declares, and `spelled` raises on None.
        providers: Sequence[OnlineMeetingProviderType | None] = (
            calendar.allowed_online_meeting_providers or []
        )
        return cls(
            uri=CalendarHandle(calendar.id).uri,
            name=calendar.name,
            owner=owner,
            is_mine=_is_signed_in(owner, signed_in),
            can_edit=calendar.can_edit,
            can_view_private_items=calendar.can_view_private_items,
            is_default=calendar.is_default_calendar,
            tracks_responses=calendar.is_tallying_responses,
            online_meeting_providers=[
                spelled(provider) for provider in providers if provider is not None
            ],
            default_online_meeting_provider=(
                None
                if calendar.default_online_meeting_provider is None
                else spelled(calendar.default_online_meeting_provider)
            ),
        )


class EventAttendee(BaseModel):
    """One person or resource invited to an event, and what they answered."""

    name: str | None = Field(
        description=(
            "The display name Microsoft holds for the attendee. Null when Graph recorded none."
        )
    )
    address: str | None = Field(
        description=(
            "The SMTP address of the attendee. This address is the value to compare and to quote. "
            + "Null when Graph recorded none."
        )
    )
    kind: str | None = Field(
        description=(
            "What kind of attendee this is, in Microsoft's own spelling: `required`, `optional` or "
            + "`resource`. A `resource` is a room or equipment mailbox that was invited as an "
            + "attendee rather than typed into the location. Null when Graph did not say."
        )
    )
    response: str | None = Field(
        description=(
            "What the attendee answered, in Microsoft's own spelling: `none`, `organizer`, "
            + "`tentativelyAccepted`, `accepted`, `declined` or `notResponded`. Microsoft "
            + "documents `none` and `notResponded` as the same fact seen from two sides, so treat "
            + "them alike. Null when Graph did not say."
        )
    )
    responded_at: str | None = Field(
        description=(
            "When the attendee answered, ISO-8601 in UTC. Null when nobody answered yet: Graph "
            + "fills the year 1 in that case, and this connector reports null instead."
        )
    )

    @classmethod
    def from_attendee(cls, attendee: Attendee) -> Self:
        status = attendee.status
        return cls(
            name=_name_of(attendee),
            address=_address_of(attendee),
            kind=None if attendee.type is None else spelled(attendee.type),
            response=(
                None if status is None or status.response is None else spelled(status.response)
            ),
            responded_at=None if status is None else _answered_at(status.time),
        )

    @classmethod
    def each_of(cls, attendees: list[Attendee] | None) -> list[Self]:
        return [cls.from_attendee(attendee) for attendee in attendees or []]


class EventSummary(BaseModel):
    """One event as every calendar tool answers it: enough to choose, never the whole body."""

    uri: str = Field(
        description=(
            "A handle for this exact event, carrying both the calendar it lives in and its own id, "
            + "each percent-encoded. Pass it verbatim to the reader. An event id belongs to one "
            + "mailbox and one calendar, so neither half addresses anything on its own."
        )
    )
    subject: str | None = Field(
        description=(
            "The subject line. Null when the event was created without one. On one calendar whose "
            + "`can_edit` and `can_view_private_items` were both false, this held the display "
            + "form of the row's own `show_as` (`Tentative` for `tentative`, `Free` for `free`) "
            + "instead of anything the organizer wrote."
        )
    )
    preview: str | None = Field(
        description=(
            "A short plain-text preview of the event body, exactly as long as Microsoft made it. "
            + "On an invitation this is often a joining block rather than what the organizer "
            + "wrote. If the preview does not answer the question, that is not evidence that the "
            + "body does not either. Null when Graph held none."
        )
    )
    start: EventTime | None = Field(
        description="When the event starts. Null when Graph stated no start."
    )
    end: EventTime | None = Field(description="When the event ends. Null when Graph stated no end.")
    all_day: bool | None = Field(
        description=(
            "Whether this is an all-day event. An all-day event runs from midnight to midnight, so "
            + "its end is the midnight after the last day it covers. When this is true, take the "
            + "date from `start.local` and never from `start.iso`."
        )
    )
    cancelled: bool | None = Field(
        description=(
            "Whether the organizer canceled the event. A canceled event stays in the calendar "
            + "until somebody removes it, so a row is canceled and listed at the same time."
        )
    )
    kind: str | None = Field(
        description=(
            "What this row is, in Microsoft's own spelling: `singleInstance`, `occurrence` or "
            + "`exception`. An `occurrence` is one date of a recurring series, and an `exception` "
            + "is one date of a series that somebody changed. Null when Graph did not say."
        )
    )
    in_series: bool = Field(
        description=(
            "Whether this row belongs to a recurring series. A weekly meeting is one row per week, "
            + "and every one of them has this set."
        )
    )
    sensitivity: str | None = Field(
        description=(
            "How the owner classified the event, in Microsoft's own spelling: `normal`, "
            + "`personal`, `private` or `confidential`. Null when Graph did not say."
        )
    )
    show_as: str | None = Field(
        description=(
            "How the event shows in the owner's free-busy view, in Microsoft's own spelling: "
            + "`free`, `tentative`, `busy`, `oof`, `workingElsewhere` or `unknown`. Null when "
            + "Graph did not say."
        )
    )
    location: str | None = Field(
        description=(
            "The location as one line of text, exactly as Microsoft holds it. It is whatever "
            + "somebody typed, so it names a room, a city, a URL, or nothing recognizable. Null "
            + "when the event carries none."
        )
    )
    is_online_meeting: bool | None = Field(
        description="Whether the event carries an online meeting. Null when Graph did not say."
    )
    join_url: str | None = Field(
        description=(
            "The link that joins the online meeting, from Graph's `onlineMeeting.joinUrl` and "
            + "never from `onlineMeetingUrl`, which Microsoft says will be deprecated. Null when "
            + "the event has no online meeting, and also when Graph withheld the joining details."
        )
    )
    organizer: MailAddress | None = Field(
        description=(
            "Who organized the event. On an event created on somebody else's behalf, this is that "
            + "person and no property names the delegate. On one calendar whose `can_edit` and "
            + "`can_view_private_items` were both false, this named the signed-in user on every "
            + "row, and one of the rows that matched by time a meeting on the user's own calendar "
            + "named somebody else there. On a calendar whose `can_edit` and "
            + "`can_view_private_items` are both false, a row whose `preview` is empty, whose "
            + "`attendee_count` is 0 and whose `subject` is the display form of its own `show_as` "
            + "has an unconfirmed organizer: do not report this name as who called the meeting. "
            + "Null when Graph recorded no organizer."
        )
    )
    owner_is_organizer: bool | None = Field(
        description=(
            "Whether the OWNER of the calendar this row was read from is the organizer of this "
            + "event. On a delegated calendar that is the other person and never the signed-in "
            + "user. Microsoft sets it for an event a delegate organized on the owner's behalf as "
            + "well, so it never says who did the organizing. Null when Graph did not say."
        )
    )
    owner_response: str | None = Field(
        description=(
            "What the OWNER of the calendar this row was read from answered, in Microsoft's own "
            + "spelling. On a delegated calendar this is the other person's answer and never the "
            + "signed-in user's. Read `attendees` for one named person's answer. Null when Graph "
            + "did not say."
        )
    )
    attendee_count: int = Field(
        description=(
            "How many attendees Graph holds for the event, the organizer included when Microsoft "
            + "lists them. Zero means Graph listed none: an appointment with nobody invited looks "
            + "like that, and so did every row of one calendar whose `can_edit` and "
            + "`can_view_private_items` were both false."
        )
    )
    web_link: str | None = Field(
        description=(
            "Graph's own link that opens the event in Outlook on the web, passed through exactly "
            + "as Graph gave it. This connector never assembles or repairs it."
        )
    )

    @classmethod
    def from_event(cls, event: Event, *, calendar_id: str, zone: ZoneInfo) -> Self:
        """Graph puts no calendar id on an event row, so `calendar_id` is passed in."""
        assert event.id is not None, "Graph answered a calendar read with an event with no id"
        status = event.response_status
        online = event.online_meeting
        return cls(
            uri=EventHandle(calendar_id, event.id).uri,
            subject=event.subject,
            preview=event.body_preview,
            start=event_time(event.start, zone=zone),
            end=event_time(event.end, zone=zone),
            all_day=event.is_all_day,
            cancelled=event.is_cancelled,
            kind=None if event.type is None else spelled(event.type),
            in_series=event.series_master_id is not None,
            sensitivity=None if event.sensitivity is None else spelled(event.sensitivity),
            show_as=None if event.show_as is None else spelled(event.show_as),
            location=None if event.location is None else event.location.display_name,
            is_online_meeting=event.is_online_meeting,
            join_url=None if online is None else online.join_url,
            organizer=MailAddress.from_recipient(event.organizer),
            owner_is_organizer=event.is_organizer,
            owner_response=(
                None if status is None or status.response is None else spelled(status.response)
            ),
            attendee_count=len(event.attendees or []),
            web_link=event.web_link,
        )


def spelled(
    value: AttendeeType
    | ResponseType
    | EventType
    | FreeBusyStatus
    | Sensitivity
    | OnlineMeetingProviderType,
) -> str:
    """TRAP: the SDK's calendar enums mix in `str` without being a `StrEnum`, so `str()` answers
    `ResponseType.None_`, and each member's trailing comma makes `.value` a one-tuple."""
    return str.__str__(value)


_TEAMS_FOR_BUSINESS = spelled(OnlineMeetingProviderType.TeamsForBusiness)


def providers_without_teams(calendar: Calendar) -> list[str] | None:
    """An empty or absent list answers None: that is Graph naming no provider rather than Graph
    refusing Teams."""
    providers: Sequence[OnlineMeetingProviderType | None] = (
        calendar.allowed_online_meeting_providers or []
    )
    allowed = [spelled(provider) for provider in providers if provider is not None]
    if not allowed or _TEAMS_FOR_BUSINESS in allowed:
        return None
    return allowed


def repeated_address(addresses: Sequence[str]) -> str | None:
    named: set[str] = set()
    for address in addresses:
        if address.casefold() in named:
            return address
        named.add(address.casefold())
    return None


async def calendar_of(client: GraphServiceClient, *, calendar_id: str | None) -> Calendar:
    """This opens no error mapping: only the calling tool knows what refusal a missing calendar
    deserves."""
    with graph_step(STEP_CALENDAR):
        found = (
            await client.me.calendar.get(
                request_configuration=RequestConfiguration[_DefaultCalendarQuery](
                    query_parameters=_DefaultCalendarQuery(select=list(CALENDAR_FIELDS))
                )
            )
            if calendar_id is None
            else await client.me.calendars.by_calendar_id(calendar_id).get(
                request_configuration=RequestConfiguration[_NamedCalendarQuery](
                    query_parameters=_NamedCalendarQuery(select=list(CALENDAR_FIELDS))
                )
            )
        )
    assert found is not None, "Graph answered a calendar read with no calendar"
    return found


@dataclass(frozen=True, slots=True)
class EventDraft:
    subject: str
    starts_at: str
    ends_at: str
    time_zone: str
    attendees: tuple[str, ...]
    optional_attendees: tuple[str, ...]
    body_html: str | None
    location: str | None
    all_day: bool
    online_meeting: bool


def draft_details(draft: EventDraft) -> str:
    return ", ".join(
        detail
        for detail in (
            _whole_days(draft) if draft.all_day else "",
            f"at {cut_for_a_question(draft.location)!r}" if draft.location else "",
            "as a Teams meeting" if draft.online_meeting else "",
            _body_described(draft.body_html) if draft.body_html else "",
        )
        if detail
    )


def _whole_days(draft: EventDraft) -> str:
    """`ends_at` is the midnight after the last day the event covers."""
    opens = wall_clock(draft.starts_at)
    closes = wall_clock(draft.ends_at)
    assert opens is not None and closes is not None, (
        "an all-day draft carries a bound no create would have accepted"
    )
    first = opens.date()
    last = closes.date() - timedelta(days=1)
    assert last >= first, "an all-day draft ends before the day it starts on"
    if last == first:
        return f"as an all-day event on {first}"
    return f"as an all-day event from {first} to {last}"


def _body_described(body_html: str) -> str:
    preview = _previewed(body_html)
    counted = f"with a body of {len(body_html)} characters"
    return f"{counted} that starts {preview!r}" if preview else counted


def _previewed(body_html: str) -> str:
    """`html.unescape` runs after the strip, so `&lt;p&gt;` reads as the text somebody escaped
    rather than as a tag."""
    read = _A_HIDDEN_ELEMENT.sub(" ", body_html)
    return cut_for_a_question(" ".join(html.unescape(_A_TAG.sub(" ", read)).split()))


def cut_for_a_question(text: str) -> str:
    if len(text) <= _PREVIEW_CHARACTERS:
        return text
    return f"{text[:_PREVIEW_CHARACTERS]}…"


def event_body(draft: EventDraft, *, transaction_id: str) -> Event:
    """An unset property is one kiota omits from the payload: `attendees: []` tells Microsoft
    there are no attendees, and no `attendees` key at all tells it nothing."""
    invited = [_invited(address, AttendeeType.Required) for address in draft.attendees] + [
        _invited(address, AttendeeType.Optional) for address in draft.optional_attendees
    ]
    return Event(
        subject=draft.subject,
        body=(
            None
            if draft.body_html is None
            else ItemBody(content=draft.body_html, content_type=BodyType.Html)
        ),
        start=DateTimeTimeZone(date_time=draft.starts_at, time_zone=draft.time_zone),
        end=DateTimeTimeZone(date_time=draft.ends_at, time_zone=draft.time_zone),
        is_all_day=draft.all_day,
        location=None if draft.location is None else Location(display_name=draft.location),
        attendees=invited or None,
        is_online_meeting=True if draft.online_meeting else None,
        online_meeting_provider=(
            OnlineMeetingProviderType.TeamsForBusiness if draft.online_meeting else None
        ),
        transaction_id=transaction_id,
    )


def transaction_id_for(target: str, draft: EventDraft) -> str:
    """Microsoft documents no comparison rule for `transactionId`, so every value the caller
    composed goes into the id; only the order of the two address lists is dropped."""
    canonical = _canonical(
        target,
        draft.subject,
        draft.starts_at,
        draft.ends_at,
        draft.time_zone,
        "all-day" if draft.all_day else "timed",
        *_listed(draft.attendees),
        *_listed(draft.optional_attendees),
        draft.location or "",
        draft.body_html or "",
        "online" if draft.online_meeting else "offline",
    )
    return str(uuid.uuid5(_TRANSACTION_NAMESPACE, canonical))


def _canonical(*fields: str) -> str:
    """Length-prefixed and unseparated: the subject, the location and the body are free text, so
    any separator character can appear inside a field and merge two drafts into one id."""
    return "".join(f"{len(field)}:{field}" for field in fields)


def _listed(addresses: tuple[str, ...]) -> list[str]:
    return [str(len(addresses)), *sorted(addresses)]


def created_event(created: Event | None) -> Event:
    """The delegated-create walkthrough answers with an `eventMessage` envelope that the SDK also
    deserializes into `Event`
    (https://learn.microsoft.com/en-us/graph/outlook-create-event-in-shared-delegated-calendar)."""
    assert created is not None, (
        "Graph answered the create with no event. The event was created, and any invitations went "
        "out. This connector cannot say which event it is."
    )
    assert created.odata_type == _AN_EVENT, (
        f"Graph answered the create with {created.odata_type}, which is not an event. The event "
        "was created, and any invitations went out. The id on this answer addresses that other "
        "resource rather than the event."
    )
    assert created.id is not None, (
        "Graph created an event it gave no id, which cannot be addressed. The event was created, "
        "and any invitations went out."
    )
    return created


def person_matches(event: Event, fragment: str) -> bool:
    wanted = fragment.casefold()
    return any(wanted in known.casefold() for known in _named_people(event))


def subject_matches(event: Event, fragment: str) -> bool:
    subject = event.subject
    return subject is not None and fragment.casefold() in subject.casefold()


def _named_people(event: Event) -> list[str]:
    people = [
        text
        for one in [_recipient_name(event.organizer), _recipient_address(event.organizer)]
        if (text := one) is not None
    ]
    for attendee in event.attendees or []:
        people.extend(
            text for one in [_name_of(attendee), _address_of(attendee)] if (text := one) is not None
        )
    return people


def _invited(address: str, kind: AttendeeType) -> Attendee:
    return Attendee(email_address=EmailAddress(address=address), type=kind)


def _is_signed_in(owner: MailAddress | None, signed_in: User | None) -> bool | None:
    """A calendar owner is stated with either the user's `mail` or their `userPrincipalName`, so
    comparing only one reports the user's own calendar as somebody else's."""
    if signed_in is None or owner is None or owner.address is None:
        return None
    mine = {
        address.casefold()
        for address in (signed_in.mail, signed_in.user_principal_name)
        if address is not None
    }
    return owner.address.casefold() in mine if mine else None


def _answered_at(moment: datetime | None) -> str | None:
    if moment is None or moment.year <= _UNANSWERED_YEAR:
        return None
    return moment.isoformat()


def _name_of(attendee: Attendee) -> str | None:
    address = attendee.email_address
    return None if address is None else address.name


def _address_of(attendee: Attendee) -> str | None:
    address = attendee.email_address
    return None if address is None else address.address


def _recipient_name(recipient: Recipient | None) -> str | None:
    address = None if recipient is None else recipient.email_address
    return None if address is None else address.name


def _recipient_address(recipient: Recipient | None) -> str | None:
    address = None if recipient is None else recipient.email_address
    return None if address is None else address.address
