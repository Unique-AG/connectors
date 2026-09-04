"""What an Outlook calendar and an Outlook event are: the shapes every calendar tool answers in.

Five tools read or write a calendar. They agree here on one shape, one `$select` list per read, and
one way to state an instant. No tool decides any of this on its own, because the difference a
caller sees is not cosmetic. A row that carries a converted timestamp from one tool and Graph's own
naive string from another reads as two different meetings.

**An instant needs three values, not one.** Graph states a start or an end as a `dateTime` string
with no offset plus a separate `timeZone` name
(https://learn.microsoft.com/en-us/graph/api/resources/datetimetimezone). Without the
`Prefer: outlook.timezone` header, Graph renders both in UTC: "If not specified, those time values
are returned in UTC" (https://learn.microsoft.com/en-us/graph/api/user-list-calendarview). No tool
here sends that header. Every tool converts with `zoneinfo` instead, and reports Graph's own two
values beside the converted one. So a caller can always see what Microsoft said, and a zone name
that `zoneinfo` cannot resolve costs the conversion and nothing else.

**`timeZone` is not always an IANA name.** Graph accepts and returns Windows zone names such as
`W. Europe Standard Time`, and it returns whatever the event was created with. `zoneinfo` has no
such key, so `EventTime.iso` is null for those and the two verbatim values still answer the
question.

**An all-day event is that same rule at its worst.** Microsoft holds both of its bounds at
midnight: "If true, regardless of whether it's a single-day or multi-day event, start, and endtime
must be set to midnight and be in the same time zone"
(https://learn.microsoft.com/en-us/graph/api/resources/event), and with no `Prefer` header that
midnight arrives in UTC. So the converted value names a time of day, and west of UTC it names the
day before. `local` is the field that answers which day such a row covers, and both descriptions
say so.

**A create is a send.** "When you create an event that includes attendees, the server sends
invitations to all attendees. This ensures consistency between the organizer's and attendees' views
of the event and can't be configured"
(https://learn.microsoft.com/en-us/graph/api/user-post-events). There is no draft state for an
event: `isDraft` on an event means unsent *updates*, not an unsent event. An event with an empty
attendee list notifies nobody. This is why `EventDraft` is named for what the caller composed and
never for something that sits on the server.

**`transactionId` is the only defense against a duplicated create.** "A custom identifier specified
by a client app for the server to avoid redundant POST operations in case of client retries to
create the same event" (https://learn.microsoft.com/en-us/graph/api/resources/event). Microsoft
documents no window and no comparison rule for it, so `transaction_id_for` derives it from every
value the draft carries: the same request composes the same id, a request that differs in the
subject, either bound, the zone, the place, the body, the guest list or the Teams setting composes
another one, and every create also runs under `no_retry()`.

**A create's response is not always an event.** Microsoft's delegated-create walkthrough answers
its step 2 with an `eventMessage` envelope
(https://learn.microsoft.com/en-us/graph/outlook-create-event-in-shared-delegated-calendar), while
`user-post-events` documents the response as an event. The SDK deserializes either one into `Event`
and records which arrived in `odata_type`, so `created_event` reads that discriminator before an
answer is composed. A message id in an event handle addresses nothing.
"""

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

# Three tools read one calendar before they read anything in it. If each one named its own step,
# one request carries three names, so they share this spelling instead.
STEP_CALENDAR = "calendar"

# Every property a calendar row reports, and nothing else. `owner` is what tells a delegated
# calendar from the user's own: Graph publishes no `isSharedWithMe` on `calendar` in v1.0, so
# "is this mine" is derived from the owner address.
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

# Every property an event row reports. `attendees` is selected for the client-side person match and
# reported as a count, because Graph documents no `$filter` over attendees.
#
# `$select` is not an optimization here. Microsoft warns that a large page with no `$select` risks a
# gateway timeout, and `body` on twenty-five events is tens of thousands of tokens nobody asked for.
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

# The widest window one listing can ask for. `calendarView` expands a recurring series into one row
# per occurrence, so a year of a daily stand-up is 250 rows of the same meeting.
MAX_WINDOW_DAYS = 92

# Required and optional attendees together, per create. Graph's own cap is 500
# (https://learn.microsoft.com/en-us/graph/api/resources/event), and this is far lower on purpose:
# every address here is a person who receives an invitation that this connector cannot recall.
MAX_ATTENDEES = 20

MAX_SUBJECT_CHARACTERS = 255

# What a single create can span. A timed event longer than a day, or an all-day event longer than
# two weeks, is usually a wrong argument rather than a wrong intention.
MAX_TIMED_EVENT_HOURS = 24
MAX_ALL_DAY_EVENT_DAYS = 14

# One local wall-clock time and nothing else: no offset, no trailing `Z`, no date on its own. The
# zone belongs in `time_zone`, which Graph reads as the zone of both bounds.
#
# `datetime.fromisoformat` is not this check. Python 3.11 widened it to the whole of ISO 8601, so
# it also reads `2026-03-02`, `2026-W10-1`, `2026-03-02 14:00`, `2026-03-02T14` and
# `20260302T140000`, and a create sends the caller's own string, so every one of those reaches
# Exchange as written. It reads `2026-03-02T24:00` as the next day's midnight too, so a pattern
# that spells the hours `\d{2}` accepts that value, `is_midnight` then agrees with it, and the
# literal `24:00` is what Exchange is asked to read. The hours stop at 23 here for that reason,
# and the minutes and the seconds at 59.
WALL_CLOCK = re.compile(r"\A\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\Z")

# Two routes reach one calendar, and the SDK generates a query-parameter class per route. These are
# aliases of the classes rather than `type` statements, because each one is also constructed.
_DefaultCalendarQuery = CalendarRequestBuilder.CalendarRequestBuilderGetQueryParameters
_NamedCalendarQuery = CalendarItemRequestBuilder.CalendarItemRequestBuilderGetQueryParameters

# The namespace `transaction_id_for` derives every id under. It is a constant of this connector: a
# new namespace makes every previously sent id unrecognizable to Graph, which is the whole point of
# sending one.
_TRANSACTION_NAMESPACE = uuid.UUID("eb6f3437-0196-4593-b4d7-a6044db0acdf")

# Graph answers `responseStatus.time` with `0001-01-01T00:00:00Z` when nobody responded. Reporting
# that year as a timestamp reads as a response from before the calendar existed.
_UNANSWERED_YEAR = 1

# Every way `zoneinfo` refuses a name, as one tuple rather than as two exception classes in an
# `except` clause. Python 3.14 accepts `except A, B:` without parentheses (PEP 758) and `ruff
# format` rewrites the parenthesized form into it, so the clause reads as a syntax error to every
# tool running an older interpreter. Naming the tuple keeps one spelling that every parser accepts.
_NO_SUCH_ZONE: tuple[type[Exception], ...] = (ZoneInfoNotFoundError, ValueError)

# What a create's response says it is. The SDK declares `Event.odata_type` with this string as its
# default and kiota leaves that default in place when a payload names no type, so every answer
# carries a type and a payload that names another one is another resource in an `Event` object.
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
    """The zone `name` addresses, or None when there is no such zone.

    `UTC` and every IANA name resolve. A Windows zone name does not. Both refusals arrive here:
    an unknown key raises `ZoneInfoNotFoundError`, and a key that is not a normalized relative
    path, such as an empty string or an absolute path, raises `ValueError` instead.
    """
    try:
        return ZoneInfo(name)
    except _NO_SUCH_ZONE:
        return None


def event_time(moment: DateTimeTimeZone | None, *, zone: ZoneInfo) -> EventTime | None:
    """One of Graph's two bounds, converted into `zone`, or None when Graph stated none.

    Graph writes `dateTime` with seven fractional digits, as in `2026-09-07T13:00:00.0000000`.
    `datetime.fromisoformat` accepts that and keeps the six digits it has room for, so the string
    goes in as it arrived.
    """
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
    """The two bounds `calendarView` requires, covering both dates whole, in `zone`.

    The end bound is the midnight that opens the day after `ends_on`, so a window whose two dates
    are the same day holds that whole day. Both bounds carry their own offset, which is what decides
    how Graph reads them: "The values of startDateTime and endDateTime are interpreted using the
    timezone offset specified in the value and aren't impacted by the value of the Prefer:
    outlook.timezone header if present. If no timezone offset is included in the value, it is
    interpreted as UTC" (https://learn.microsoft.com/en-us/graph/api/user-list-calendarview).
    """
    opens = datetime.combine(starts_on, time.min, tzinfo=zone)
    closes = datetime.combine(ends_on + timedelta(days=1), time.min, tzinfo=zone)
    return opens.isoformat(timespec="seconds"), closes.isoformat(timespec="seconds")


def wall_clock(value: str) -> datetime | None:
    """`value` as a naive datetime when it is one wall-clock time, and None when it is not.

    Both creates check the order and the length of an event with this, and neither sends it: the
    value that reaches Graph is the caller's own string, because Microsoft reads `dateTime` beside
    the `timeZone` name and reformatting the string changes which instant the event is at.

    One speller for two tools. A second one accepts a shape the first refuses, and every shape a
    create accepts is a shape Exchange is asked to read.
    """
    if WALL_CLOCK.match(value) is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_midnight(moment: datetime) -> bool:
    """Whether `moment` is midnight, which is where Microsoft requires both bounds of an all-day
    event: "If true, regardless of whether it's a single-day or multi-day event, start, and endtime
    must be set to midnight and be in the same time zone"
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
        """`signed_in` is passed in rather than read: a tool that reads no `/me` has no way to
        answer `is_mine`, and passing None there says so."""
        assert calendar.id is not None, "Graph answered a calendar read with a calendar with no id"
        owner = MailAddress.from_email_address(calendar.owner)
        # kiota deserializes a provider this SDK has no member for, a future `someNewProvider`
        # say, as None inside the list, whatever the SDK declares, and `spelled` raises on None.
        # So the list is read as one that holds them, and a provider the SDK cannot name is left
        # out. The same fact answers `default_online_meeting_provider` null.
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
            + "`resource`. A `resource` is a room or equipment mailbox, which Exchange can add on "
            + "its own when a location matches a bookable room. Null when Graph did not say."
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
        """`calendar_id` is passed in rather than read off `event`: the calendar an event was read
        from is half of its handle, and Graph puts no calendar id on the row."""
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
    """Microsoft's own spelling for one of the calendar enums this connector echoes.

    TRAP: neither `.value` nor `str()` is the way to read these. Every member of the SDK's
    `AttendeeType`, `ResponseType`, `EventType`, `FreeBusyStatus`, `Sensitivity` and
    `OnlineMeetingProviderType` is declared with a trailing comma. A type checker sees a one-tuple
    because of that comma. And all of them mix in `str` without being a `StrEnum`, so `str()`
    answers `ResponseType.None_` instead of `none`. `ResponseType.None_` also carries a trailing
    underscore, which is the Python keyword and not Graph's spelling.
    """
    return str.__str__(value)


# The provider a create asks for, read through `spelled` rather than written out here, so the
# comparison and the payload carry one spelling. It is below `spelled` because it calls it.
_TEAMS_FOR_BUSINESS = spelled(OnlineMeetingProviderType.TeamsForBusiness)


def providers_without_teams(calendar: Calendar) -> list[str] | None:
    """The online-meeting providers this calendar allows, when Teams is not one of them, else None.

    Both creates read the calendar before they write, so this answer costs no request of its own.
    The spellings are Microsoft's, so a refusal names the providers as the user's own admin sees
    them.

    An empty or an absent list is not evidence and answers None: it is Graph naming no provider
    rather than Graph refusing Teams. Only a list that names other providers refuses.

    kiota deserializes a provider this SDK has no member for, a future `someNewProvider` say, as
    None inside the list, whatever the SDK declares. Those are skipped, so a list of nothing but
    providers the SDK cannot name is not evidence either and answers None rather than refusing a
    calendar over a provider this connector cannot even print.
    """
    providers: Sequence[OnlineMeetingProviderType | None] = (
        calendar.allowed_online_meeting_providers or []
    )
    allowed = [spelled(provider) for provider in providers if provider is not None]
    if not allowed or _TEAMS_FOR_BUSINESS in allowed:
        return None
    return allowed


def repeated_address(addresses: Sequence[str]) -> str | None:
    """The first entry that names an address the list already named, verbatim, else None.

    Both creates refuse a repeated address, so one speller keeps the two lists they accept the
    same. Case is not a second person, so the comparison is casefolded.
    """
    named: set[str] = set()
    for address in addresses:
        if address.casefold() in named:
            return address
        named.add(address.casefold())
    return None


async def calendar_of(client: GraphServiceClient, *, calendar_id: str | None) -> Calendar:
    """The calendar `calendar_id` addresses, or the mailbox's own primary calendar when it is None.

    This function opens no error mapping. The refusal a missing calendar deserves depends on where
    the id came from, and only the calling tool knows that.
    """
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
    """What a caller composed, after the calling tool validated every argument.

    "Draft" names this side of the wire only. Microsoft has no unsent event: the POST creates the
    event and sends every invitation.
    """

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


def event_body(draft: EventDraft, *, transaction_id: str) -> Event:
    """The `Event` a create posts. Anything the draft did not name is left unset.

    An unset property is one kiota omits from the payload, and an omitted property is not the same
    request as an explicit null: `attendees: []` on a create is Microsoft being told there are no
    attendees, and no `attendees` key at all is Microsoft being told nothing. This function sets no
    `hideAttendees`, `recurrence`, `responseRequested`, `allowNewTimeProposals` or `attachments`,
    because no tool here offers any of them.

    The zone goes on the wire exactly as the caller gave it. Graph accepts every Windows zone name
    here and a fixed list of IANA names
    (https://learn.microsoft.com/en-us/graph/api/resources/datetimetimezone), Exchange answers a
    name outside both with an error, and a translation here changes which instant the event is at.
    """
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
    """The `transactionId` this draft is created under, derived from the draft itself.

    Every value a caller composed goes into the canonical string: the target, the subject, both
    bounds, the zone, all-day, the two address lists, the location, the body and whether the
    meeting is online. Only the order of the addresses is dropped, because the same invitation
    arrives with the people listed in whatever order a model wrote them in.

    Nothing is left out on purpose. Microsoft documents no comparison rule for the id, so a server
    that drops a second POST as redundant leaves the first request's room and agenda on the
    calendar, and a request that differs in anything a person named has to differ here too.
    `target` is what tells two calendars apart, so the same draft on two calendars is two events.
    """
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
    """Every field with its own length written in front of it, and no separator at all.

    A separator is not enough here. The subject, the location and the body are free text a person
    wrote, and whatever character a separator uses can appear inside one of them, so a location
    that carries the separator moves the boundary and two different drafts compose one id. A
    length says where a field ends whatever the field holds.
    """
    return "".join(f"{len(field)}:{field}" for field in fields)


def _listed(addresses: tuple[str, ...]) -> list[str]:
    """One address list as its own count and then its addresses, sorted.

    The order is dropped because the same invitation arrives with the people listed in whatever
    order a model wrote them in. The count is a field of its own, so moving one address from the
    required list to the optional one still composes another id.
    """
    return [str(len(addresses)), *sorted(addresses)]


def created_event(created: Event | None) -> Event:
    """Graph's answer to a create, once it is an event this connector can address.

    Microsoft's delegated-create walkthrough shows the response as an `eventMessage` envelope with
    the event nested under an `event` key
    (https://learn.microsoft.com/en-us/graph/outlook-create-event-in-shared-delegated-calendar),
    and `user-post-events` documents it as an event. The SDK deserializes both into `Event`, so an
    unchecked answer reports a message id as the event handle and an empty attendee list as nobody
    invited.

    The type is compared against the event type alone. A null type is not accepted and is also not
    reachable: the SDK declares `Event.odata_type` with `#microsoft.graph.event` as its default,
    and kiota leaves that default in place when a payload names no type, so every answer that
    deserializes into `Event` carries a type.

    Every assertion here fires after the write, which is why each message says the event exists.
    An internal error at this point is not "nothing happened".
    """
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
    """Whether `fragment` appears in the organizer's or any attendee's name or address.

    This is a client-side predicate because Graph documents no `$filter` over `attendees` on
    `calendarView`. Case is ignored, and the comparison is a substring, so `ada` matches
    `ada@example.invalid` and `Adam`.
    """
    wanted = fragment.casefold()
    return any(wanted in known.casefold() for known in _named_people(event))


def subject_matches(event: Event, fragment: str) -> bool:
    """Whether `fragment` appears in the subject. Case is ignored."""
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
    """Whether the owner address is one of the signed-in user's two addresses.

    Graph gives a user both a `mail` and a `userPrincipalName`, and a calendar owner is stated with
    one of them. Comparing only one reports a user's own calendar as somebody else's.
    """
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
