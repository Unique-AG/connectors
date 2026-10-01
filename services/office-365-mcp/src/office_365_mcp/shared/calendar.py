import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.attendee import Attendee
from msgraph.generated.models.attendee_type import AttendeeType
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.calendar import Calendar
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.day_of_week import DayOfWeek
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.event import Event
from msgraph.generated.models.event_type import EventType
from msgraph.generated.models.free_busy_status import FreeBusyStatus
from msgraph.generated.models.importance import Importance
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.location import Location
from msgraph.generated.models.online_meeting_provider_type import OnlineMeetingProviderType
from msgraph.generated.models.response_type import ResponseType
from msgraph.generated.models.sensitivity import Sensitivity
from msgraph.generated.models.user import User
from msgraph.generated.models.working_hours import WorkingHours
from msgraph.generated.users.item.calendar.calendar_request_builder import CalendarRequestBuilder
from msgraph.generated.users.item.calendars.item.calendar_item_request_builder import (
    CalendarItemRequestBuilder,
)
from msgraph.generated.users.item.calendars.item.events.item.event_item_request_builder import (
    EventItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_step
from office_365_mcp.shared.handles import CalendarHandle, EventHandle
from office_365_mcp.shared.immutable_ids import immutable_id_headers
from office_365_mcp.shared.mail import MailAddress
from office_365_mcp.shared.prose import body_opening as body_opening
from office_365_mcp.shared.prose import cut_for_a_question as cut_for_a_question
from office_365_mcp.shared.window import closes_at, opens_at

STEP_CALENDAR = "calendar"
STEP_EVENT = "calendar_event"

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
    "categories",
    "importance",
    "recurrence",
)

NOBODY_INVITED_BUT_A_PLACE = (
    "No person is invited. But Microsoft can send the meeting request to the mailbox of a room, "
    + "or of a bookable room that the location names."
)

SHOW_AS_FIELD = (
    "How the event shows in the free-busy view of the calendar: `free`, `tentative`, `busy`, "
    + "`oof` for out of office, or `workingElsewhere`. Null sends nothing, and Microsoft then "
    + "applies its own default."
)

CATEGORIES_FIELD = (
    "One category name for each entry, exactly as the user names it or as outlook_list_categories "
    + "reports it. An empty list adds no category to the event."
)

IMPORTANCE_FIELD = (
    "The importance of the event: `low`, `normal`, or `high`. Null sends nothing, and Microsoft "
    + "then applies its own default."
)

SENSITIVITY_FIELD = (
    "The sensitivity of the event: `normal`, `personal`, `private`, or `confidential`. Null "
    + "sends nothing, and Microsoft then applies its own default."
)

ROOM_ADDRESSES_FIELD = (
    "The rooms to book, one SMTP address of a room mailbox for each entry and nothing else in the "
    + "entry. Take each address from the user. This tool adds each room as a `resource` attendee, "
    + "and the mailbox of each room gets the meeting request. An address must not repeat, and "
    + "must not also be in `attendees` or `optional_attendees`."
)

IS_REMINDER_ON_FIELD = (
    "Set this parameter to true for a reminder alert before the event starts, or to false for no "
    + "reminder. Null sends nothing, and Microsoft then applies its own default."
)

REMINDER_MINUTES_FIELD = (
    "How many minutes before the start the reminder alert comes, as a whole number of 0 or more. "
    + "Null sends nothing, and Microsoft then applies its own default."
)

HIDE_ATTENDEES_FIELD = (
    "Set this parameter to true to hide the attendee list. Each attendee then sees only "
    + "themselves in the meeting request and in the tracking list. Null sends nothing, and "
    + "Microsoft then uses false, so every attendee sees the full list."
)

RESPONSE_REQUESTED_FIELD = (
    "Set this parameter to false to ask the attendees for no response to the invitation. Null "
    + "sends nothing, and Microsoft then uses true, so each attendee is asked for a response."
)

ALLOW_NEW_TIME_PROPOSALS_FIELD = (
    "Set this parameter to false so that attendees cannot propose a new time when they respond. "
    + "Null sends nothing, and Microsoft then uses true, so attendees can propose a new time."
)

STORED_SHOW_AS_FIELD = (
    "The free-busy status as Microsoft stored it, read from the response and not from the "
    + "arguments. Microsoft can also report `unknown`. This field is null when Graph did not say."
)

STORED_CATEGORIES_FIELD = (
    "The categories as Microsoft stored them, read from the response and not from the "
    + "arguments. The list is empty when the event has no category."
)

STORED_IMPORTANCE_FIELD = (
    "The importance as Microsoft stored it: `low`, `normal`, or `high`. This field is null when "
    + "Graph returned no importance."
)

STORED_SENSITIVITY_FIELD = (
    "The sensitivity as Microsoft stored it: `normal`, `personal`, `private`, or `confidential`. "
    + "This field is null when Graph returned no sensitivity."
)

STORED_IS_REMINDER_ON_FIELD = (
    "Whether Microsoft stored a reminder alert for the event, read from the response and not from "
    + "the arguments. This field is null when Graph did not say."
)

STORED_REMINDER_MINUTES_FIELD = (
    "How many minutes before the start the reminder alert comes, as Microsoft stored it. This "
    + "field is null when Graph did not say."
)

STORED_HIDE_ATTENDEES_FIELD = (
    "Whether each attendee sees only themselves in the meeting request, as Microsoft stored it. "
    + "This field is null when Graph did not say."
)

STORED_RESPONSE_REQUESTED_FIELD = (
    "Whether the invitation asks each attendee for a response, as Microsoft stored it. This field "
    + "is null when Graph did not say."
)

STORED_ALLOW_NEW_TIME_PROPOSALS_FIELD = (
    "Whether the attendees can propose a new time, as Microsoft stored it. This field is null "
    + "when Graph did not say."
)

WALL_CLOCK = re.compile(r"\A\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\Z")

ZONE_NAME = r"^[A-Za-z0-9][A-Za-z0-9 _./+-]*$"

_DefaultCalendarQuery = CalendarRequestBuilder.CalendarRequestBuilderGetQueryParameters
_NamedCalendarQuery = CalendarItemRequestBuilder.CalendarItemRequestBuilderGetQueryParameters
_EventItemQuery = EventItemRequestBuilder.EventItemRequestBuilderGetQueryParameters

_TRANSACTION_NAMESPACE = uuid.UUID("eb6f3437-0196-4593-b4d7-a6044db0acdf")

_UNANSWERED_YEAR = 1

_NO_SUCH_ZONE: tuple[type[Exception], ...] = (ZoneInfoNotFoundError, ValueError)

_AN_EVENT = "#microsoft.graph.event"

type PatternType = Literal[
    "daily", "weekly", "absoluteMonthly", "relativeMonthly", "absoluteYearly", "relativeYearly"
]

type DayName = Literal["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]

type WeekIndexName = Literal["first", "second", "third", "fourth", "last"]

type RangeType = Literal["endDate", "noEnd", "numbered"]

type ShowAs = Literal["free", "tentative", "busy", "oof", "workingElsewhere"]

type EventImportance = Literal["low", "normal", "high"]

type EventSensitivity = Literal["normal", "personal", "private", "confidential"]

_SHOWN_AS: Mapping[ShowAs, str] = {
    "free": "free",
    "tentative": "tentative",
    "busy": "busy",
    "oof": "out of office",
    "workingElsewhere": "working elsewhere",
}


class EventTime(BaseModel):
    local: str = Field(description="The wall-clock time Graph holds for this event, no offset.")
    time_zone: str | None = Field(description="The zone name for `local`, or null if none.")
    iso: str | None = Field(
        description=(
            "The same instant as an ISO-8601 timestamp with an offset, for comparing and "
            + "sorting; null when the zone cannot be resolved."
        )
    )


def zone_named(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except _NO_SUCH_ZONE:
        return None


def event_time(moment: DateTimeTimeZone | None, *, zone: ZoneInfo) -> EventTime | None:
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


def window_bounds(
    starts_on: date | datetime, ends_on: date | datetime, *, zone: ZoneInfo
) -> tuple[str, str]:
    opens = opens_at(starts_on, zone=zone)
    closes = (
        closes_at(ends_on, zone=zone)
        if isinstance(ends_on, datetime)
        else opens_at(ends_on + timedelta(days=1), zone=zone)
    )
    return opens.isoformat(timespec="seconds"), closes.isoformat(timespec="seconds")


def wall_clock(value: str) -> datetime | None:
    if WALL_CLOCK.match(value) is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_midnight(moment: datetime) -> bool:
    return moment.time() == time.min


class CalendarSummary(BaseModel):
    uri: str = Field(description="A handle for this calendar; pass it as `calendar_ref`.")
    name: str | None = Field(description="The calendar's name, or null if none.")
    owner: MailAddress | None = Field(description="Whose calendar this is, or null if none.")
    is_mine: bool | None = Field(
        description="Whether the owner is the signed-in user, or null if unknown."
    )
    can_edit: bool | None = Field(
        description="Whether the signed-in user can write to this calendar."
    )
    can_view_private_items: bool | None = Field(
        description="Whether the signed-in user sees private items' details."
    )
    is_default: bool | None = Field(description="Whether this is the mailbox's primary calendar.")
    tracks_responses: bool | None = Field(
        description="Whether this calendar tallies attendee responses."
    )
    online_meeting_providers: list[str] = Field(
        description="The online-meeting providers this calendar accepts."
    )
    default_online_meeting_provider: str | None = Field(
        description="The provider a new online meeting on this calendar uses, or null if none."
    )

    @classmethod
    def from_calendar(cls, calendar: Calendar, *, signed_in: User | None) -> Self:
        assert calendar.id is not None, "Graph answered a calendar read with a calendar with no id"
        owner = MailAddress.from_email_address(calendar.owner)
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
    name: str | None = Field(description="The attendee's display name, or null if none.")
    address: str | None = Field(description="The attendee's SMTP address, or null if none.")
    kind: str | None = Field(
        description="The attendee kind: `required`, `optional`, or `resource`; null if unknown."
    )
    response: str | None = Field(description="What the attendee answered, or null if unknown.")
    responded_at: str | None = Field(
        description="When the attendee answered, in ISO-8601 UTC, or null if not yet."
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
    uri: str = Field(description="A handle for this event; pass it, verbatim, to the reader.")
    subject: str | None = Field(description="The subject line, or null if none.")
    preview: str | None = Field(
        description="A short plain-text preview of the event body, or null if none."
    )
    start: EventTime | None = Field(description="When the event starts, or null if unstated.")
    end: EventTime | None = Field(description="When the event ends, or null if unstated.")
    all_day: bool | None = Field(description="Whether this is an all-day event.")
    cancelled: bool | None = Field(description="Whether the organizer cancelled the event.")
    kind: str | None = Field(
        description="The row kind: `singleInstance`, `occurrence`, or `exception`; null if unknown."
    )
    in_series: bool = Field(description="Whether this row belongs to a recurring series.")
    sensitivity: str | None = Field(
        description="How the owner classified the event, or null if unknown."
    )
    show_as: str | None = Field(
        description="How the event shows in the owner's free-busy view, or null if unknown."
    )
    location: str | None = Field(description="The location as one line of text, or null if none.")
    is_online_meeting: bool | None = Field(
        description="Whether the event carries an online meeting, or null if unknown."
    )
    join_url: str | None = Field(
        description="The link that joins the online meeting, or null if none."
    )
    organizer: MailAddress | None = Field(description="Who organized the event, or null if none.")
    owner_is_organizer: bool | None = Field(
        description="Whether the calendar owner is the organizer, or null if unknown."
    )
    owner_response: str | None = Field(
        description="What the calendar owner answered, or null if unknown."
    )
    attendee_count: int = Field(
        description="How many attendees Graph holds for the event, the organizer included."
    )
    web_link: str | None = Field(description="A link that opens the event in Outlook on the web.")

    @classmethod
    def from_event(cls, event: Event, *, calendar_id: str, zone: ZoneInfo) -> Self:
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


class WorkingHoursSummary(BaseModel):
    days: list[str] = Field(
        description=(
            "The weekdays on which the owner works, in lowercase English, for example "
            + "`monday`. This list is empty when Graph names no day."
        )
    )
    starts_at: str | None = Field(
        description=(
            "The time of day at which the owner starts work, for example `08:00:00`. It has no "
            + "offset and is a wall-clock time in `time_zone`. This field is null when Graph "
            + "gives no time."
        )
    )
    ends_at: str | None = Field(
        description=(
            "The time of day at which the owner stops work. It has the same form and zone as "
            + "`starts_at`. This field is null when Graph gives no time."
        )
    )
    time_zone: str | None = Field(
        description=(
            "The name of the zone that `starts_at` and `ends_at` use, as Microsoft spells it. "
            + "It is a standard zone name such as `Pacific Standard Time`, or `Customized Time "
            + "Zone` for a custom zone. This field is null when Graph gives no name."
        )
    )

    @classmethod
    def from_working_hours(cls, hours: WorkingHours | None) -> Self | None:
        if hours is None:
            return None
        days: Sequence[DayOfWeek | None] = hours.days_of_week or []
        zone = hours.time_zone
        return cls(
            days=[spelled(day) for day in days if day is not None],
            starts_at=None if hours.start_time is None else hours.start_time.isoformat(),
            ends_at=None if hours.end_time is None else hours.end_time.isoformat(),
            time_zone=None if zone is None else zone.name,
        )


def spelled(
    value: AttendeeType
    | DayOfWeek
    | ResponseType
    | EventType
    | FreeBusyStatus
    | Sensitivity
    | Importance
    | OnlineMeetingProviderType,
) -> str:
    return str.__str__(value)


_TEAMS_FOR_BUSINESS = spelled(OnlineMeetingProviderType.TeamsForBusiness)


def providers_without_teams(calendar: Calendar) -> list[str] | None:
    providers: Sequence[OnlineMeetingProviderType | None] = (
        calendar.allowed_online_meeting_providers or []
    )
    allowed = [spelled(provider) for provider in providers if provider is not None]
    if not allowed or _TEAMS_FOR_BUSINESS in allowed:
        return None
    return allowed


def resource_addresses(event: Event) -> tuple[str, ...]:
    return tuple(
        attendee.email_address.address
        for attendee in event.attendees or []
        if attendee.type == AttendeeType.Resource
        and attendee.email_address is not None
        and attendee.email_address.address is not None
    )


def repeated_address(addresses: Sequence[str]) -> str | None:
    named: set[str] = set()
    for address in addresses:
        if address.casefold() in named:
            return address
        named.add(address.casefold())
    return None


async def event_of(client: GraphServiceClient, *, calendar_id: str, event_id: str) -> Event:
    with graph_step(STEP_EVENT):
        found = (
            await client.me.calendars.by_calendar_id(calendar_id)
            .events.by_event_id(event_id)
            .get(
                request_configuration=RequestConfiguration[_EventItemQuery](
                    query_parameters=_EventItemQuery(select=list(SUMMARY_FIELDS)),
                    headers=immutable_id_headers(),
                )
            )
        )
    assert found is not None, "Graph answered an event read with no event"
    return found


async def calendar_of(client: GraphServiceClient, *, calendar_id: str | None) -> Calendar:
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
    room_addresses: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    show_as: ShowAs | None = None
    importance: EventImportance | None = None
    sensitivity: EventSensitivity | None = None
    is_reminder_on: bool | None = None
    reminder_minutes_before_start: int | None = None
    hide_attendees: bool | None = None
    response_requested: bool | None = None
    allow_new_time_proposals: bool | None = None


def draft_details(draft: EventDraft) -> str:
    return ", ".join(
        detail
        for detail in (
            _whole_days(draft) if draft.all_day else "",
            f"at {cut_for_a_question(draft.location)!r}" if draft.location else "",
            _rooms_booked(draft.room_addresses),
            "as a Teams meeting" if draft.online_meeting else "",
            "" if draft.show_as is None else f"shown as {_SHOWN_AS[draft.show_as]}",
            "" if draft.importance is None else f"with {draft.importance} importance",
            "" if draft.sensitivity is None else f"marked as {draft.sensitivity}",
            (
                f"tagged {cut_for_a_question(', '.join(draft.categories))!r}"
                if draft.categories
                else ""
            ),
            _reminder(draft.is_reminder_on, draft.reminder_minutes_before_start),
            _either(
                draft.hide_attendees,
                yes="with the attendee list hidden",
                no="with the attendee list visible to every attendee",
            ),
            _either(
                draft.response_requested,
                yes="with a response requested",
                no="with no response requested",
            ),
            _either(
                draft.allow_new_time_proposals,
                yes="with new time proposals allowed",
                no="with no new time proposals allowed",
            ),
            _body_described(draft.body_html) if draft.body_html else "",
        )
        if detail
    )


def _rooms_booked(rooms: tuple[str, ...]) -> str:
    if not rooms:
        return ""
    return f"booking the {'room' if len(rooms) == 1 else 'rooms'} {', '.join(rooms)}"


def _reminder(on: bool | None, minutes: int | None) -> str:
    if minutes is None:
        return _either(on, yes="with a reminder", no="with no reminder")
    before = f"{minutes} {'minute' if minutes == 1 else 'minutes'} before the start"
    if on is False:
        return f"with no reminder, and a reminder time of {before}"
    return f"with a reminder {before}"


def _either(value: bool | None, *, yes: str, no: str) -> str:
    if value is None:
        return ""
    return yes if value else no


def _whole_days(draft: EventDraft) -> str:
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
    preview = body_opening(body_html)
    counted = f"with a body of {len(body_html)} characters"
    return f"{counted} that starts {preview!r}" if preview else counted


def event_body(draft: EventDraft, *, transaction_id: str) -> Event:
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
        attendees=[
            *invited_attendees(draft.attendees, draft.optional_attendees),
            *(invited_attendee(room, AttendeeType.Resource) for room in draft.room_addresses),
        ]
        or None,
        is_online_meeting=True if draft.online_meeting else None,
        online_meeting_provider=(
            OnlineMeetingProviderType.TeamsForBusiness if draft.online_meeting else None
        ),
        categories=list(draft.categories) or None,
        show_as=None if draft.show_as is None else FreeBusyStatus(draft.show_as),
        importance=None if draft.importance is None else Importance(draft.importance),
        sensitivity=None if draft.sensitivity is None else Sensitivity(draft.sensitivity),
        is_reminder_on=draft.is_reminder_on,
        reminder_minutes_before_start=draft.reminder_minutes_before_start,
        hide_attendees=draft.hide_attendees,
        response_requested=draft.response_requested,
        allow_new_time_proposals=draft.allow_new_time_proposals,
        transaction_id=transaction_id,
    )


@dataclass(frozen=True, slots=True)
class EventPatch:
    subject: str | None
    starts_at: str | None
    ends_at: str | None
    time_zone: str | None
    location: str | None
    attendees: tuple[str, ...] | None
    optional_attendees: tuple[str, ...] | None


def event_patch_body(patch: EventPatch) -> Event:
    assert (patch.attendees is None) == (patch.optional_attendees is None), (
        "attendees and optional_attendees are resolved to a full replacement list together, "
        "never one without the other, before an EventPatch is built"
    )
    return Event(
        subject=patch.subject,
        start=(
            None
            if patch.starts_at is None
            else DateTimeTimeZone(date_time=patch.starts_at, time_zone=patch.time_zone)
        ),
        end=(
            None
            if patch.ends_at is None
            else DateTimeTimeZone(date_time=patch.ends_at, time_zone=patch.time_zone)
        ),
        location=None if patch.location is None else Location(display_name=patch.location),
        attendees=(
            None
            if patch.attendees is None
            else invited_attendees(patch.attendees, patch.optional_attendees or ())
        ),
    )


def confirmation_id_for(target: str, *fields: str) -> str:
    return str(uuid.uuid5(_TRANSACTION_NAMESPACE, _canonical(target, *fields)))


def transaction_id_for(target: str, draft: EventDraft) -> str:
    return confirmation_id_for(
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
        *_options(draft),
    )


def _options(draft: EventDraft) -> list[str]:
    chosen = (
        draft.show_as,
        draft.importance,
        draft.sensitivity,
        draft.is_reminder_on,
        draft.reminder_minutes_before_start,
        draft.hide_attendees,
        draft.response_requested,
        draft.allow_new_time_proposals,
    )
    if all(one is None for one in chosen) and not draft.categories and not draft.room_addresses:
        return []
    return [
        *(repr(one) for one in chosen),
        *_listed(draft.categories),
        *_listed(draft.room_addresses),
    ]


def _canonical(*fields: str) -> str:
    return "".join(f"{len(field)}:{field}" for field in fields)


def _listed(addresses: tuple[str, ...]) -> list[str]:
    return [str(len(addresses)), *sorted(addresses)]


def created_event(created: Event | None) -> Event:
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


def invited_attendee(address: str, kind: AttendeeType) -> Attendee:
    return Attendee(email_address=EmailAddress(address=address), type=kind)


def counted_people(addresses: Sequence[str]) -> str:
    return "1 person" if len(addresses) == 1 else f"{len(addresses)} people"


def invited_attendees(required: Sequence[str], optional: Sequence[str]) -> list[Attendee]:
    return [invited_attendee(address, AttendeeType.Required) for address in required] + [
        invited_attendee(address, AttendeeType.Optional) for address in optional
    ]


def _is_signed_in(owner: MailAddress | None, signed_in: User | None) -> bool | None:
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
