import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
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
from msgraph.generated.users.item.calendars.item.events.item.event_item_request_builder import (
    EventItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_step
from office_365_mcp.shared.handles import CalendarHandle, EventHandle
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
)

MAX_ATTENDEES = 20

MAX_SUBJECT_CHARACTERS = 255

MAX_LOCATION_CHARACTERS = 255

NOBODY_INVITED_BUT_A_PLACE = (
    "Nobody is invited, and a location that names a bookable room can reach that room's mailbox."
)

MAX_TIMED_EVENT_HOURS = 24
MAX_ALL_DAY_EVENT_DAYS = 14

WALL_CLOCK = re.compile(r"\A\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\Z")

ZONE_NAME = r"^[A-Za-z0-9][A-Za-z0-9 _./+-]*$"

MAX_ZONE_CHARACTERS = 64

_DefaultCalendarQuery = CalendarRequestBuilder.CalendarRequestBuilderGetQueryParameters
_NamedCalendarQuery = CalendarItemRequestBuilder.CalendarItemRequestBuilderGetQueryParameters
_EventItemQuery = EventItemRequestBuilder.EventItemRequestBuilderGetQueryParameters

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_TRANSACTION_NAMESPACE = uuid.UUID("eb6f3437-0196-4593-b4d7-a6044db0acdf")

_UNANSWERED_YEAR = 1

_NO_SUCH_ZONE: tuple[type[Exception], ...] = (ZoneInfoNotFoundError, ValueError)

_AN_EVENT = "#microsoft.graph.event"


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


def spelled(
    value: AttendeeType
    | ResponseType
    | EventType
    | FreeBusyStatus
    | Sensitivity
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


def immutable_id_headers() -> HeadersCollection:
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return headers


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
        attendees=invited_attendees(draft.attendees, draft.optional_attendees) or None,
        is_online_meeting=True if draft.online_meeting else None,
        online_meeting_provider=(
            OnlineMeetingProviderType.TeamsForBusiness if draft.online_meeting else None
        ),
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
    )


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


def _recipient_name(recipient: Recipient | None) -> str | None:
    address = None if recipient is None else recipient.email_address
    return None if address is None else address.name


def _recipient_address(recipient: Recipient | None) -> str | None:
    address = None if recipient is None else recipient.email_address
    return None if address is None else address.address
