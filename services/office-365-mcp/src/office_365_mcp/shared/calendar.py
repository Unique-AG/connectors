import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import ClassVar, Literal, Self, cast
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
from msgraph.generated.models.patterned_recurrence import PatternedRecurrence
from msgraph.generated.models.recurrence_pattern import RecurrencePattern
from msgraph.generated.models.recurrence_pattern_type import RecurrencePatternType
from msgraph.generated.models.recurrence_range import RecurrenceRange
from msgraph.generated.models.recurrence_range_type import RecurrenceRangeType
from msgraph.generated.models.sensitivity import Sensitivity
from msgraph.generated.models.user import User
from msgraph.generated.models.week_index import WeekIndex
from msgraph.generated.models.working_hours import WorkingHours
from msgraph.generated.users.item.calendar.calendar_request_builder import CalendarRequestBuilder
from msgraph.generated.users.item.calendars.item.calendar_item_request_builder import (
    CalendarItemRequestBuilder,
)
from msgraph.generated.users.item.calendars.item.events.item.event_item_request_builder import (
    EventItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, ConfigDict, Field, field_validator

from office_365_mcp.graph_client import graph_step
from office_365_mcp.shared.categories import LIST_CATEGORIES_GUARD
from office_365_mcp.shared.handles import CalendarHandle, EventHandle
from office_365_mcp.shared.immutable_ids import immutable_id_headers
from office_365_mcp.shared.mail import MailAddress
from office_365_mcp.shared.odata import spelled
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
)

NOBODY_INVITED_BUT_A_PLACE = (
    "No person is invited. But Microsoft can send the meeting request to the mailbox of a room, "
    + "or of a bookable room that the location names."
)

NOBODY_INVITED_BUT_A_ROOM = (
    "No person is invited. Microsoft sends the meeting request to the mailbox of each room when "
    + "it creates the event. This connector cannot recall it."
)

_DEFAULT_WHEN_NULL = " Null sends nothing, and Microsoft then applies its own default."

_KEPT_WHEN_NULL = " Null sends nothing, and the event keeps the value that it has now."

_SHOW_AS = (
    "How the event shows in the free-busy view of the calendar: `free`, `tentative`, `busy`, "
    + "`oof` for out of office, or `workingElsewhere`."
)

SHOW_AS_FIELD = _SHOW_AS + _DEFAULT_WHEN_NULL

SHOW_AS_CHANGE_FIELD = _SHOW_AS + _KEPT_WHEN_NULL

CATEGORIES_FIELD = (
    "One category name for each entry, exactly as the user names it. "
    + LIST_CATEGORIES_GUARD
    + " An empty list adds no category to the event."
)

_IMPORTANCE = "The importance of the event: `low`, `normal`, or `high`."

IMPORTANCE_FIELD = _IMPORTANCE + _DEFAULT_WHEN_NULL

IMPORTANCE_CHANGE_FIELD = _IMPORTANCE + _KEPT_WHEN_NULL

_SENSITIVITY = "The sensitivity of the event: `normal`, `personal`, `private`, or `confidential`."

SENSITIVITY_FIELD = _SENSITIVITY + _DEFAULT_WHEN_NULL

SENSITIVITY_CHANGE_FIELD = _SENSITIVITY + _KEPT_WHEN_NULL

ROOM_ADDRESSES_FIELD = (
    "The rooms to book, one SMTP address of a room mailbox for each entry and nothing else in the "
    + "entry. Take each address from the user. This tool adds each room as a `resource` attendee, "
    + "and the mailbox of each room gets the meeting request. An address must not repeat, and "
    + "must not also be in `attendees` or `optional_attendees`."
)

_IS_REMINDER_ON = (
    "Set this parameter to true for a reminder alert before the event starts, or to false for no "
    + "reminder."
)

IS_REMINDER_ON_FIELD = _IS_REMINDER_ON + _DEFAULT_WHEN_NULL

IS_REMINDER_ON_CHANGE_FIELD = _IS_REMINDER_ON + _KEPT_WHEN_NULL

_REMINDER_MINUTES = (
    "How many minutes before the start the reminder alert comes, as a whole number of 0 or more."
)

REMINDER_MINUTES_FIELD = _REMINDER_MINUTES + _DEFAULT_WHEN_NULL

REMINDER_MINUTES_CHANGE_FIELD = _REMINDER_MINUTES + _KEPT_WHEN_NULL

_HIDE_ATTENDEES = (
    "Set this parameter to true to hide the attendee list. Each attendee then sees only "
    + "themselves in the meeting request and in the tracking list."
)

HIDE_ATTENDEES_FIELD = (
    _HIDE_ATTENDEES
    + " Null sends nothing, and Microsoft then uses false, so every attendee sees the full list."
)

HIDE_ATTENDEES_CHANGE_FIELD = _HIDE_ATTENDEES + _KEPT_WHEN_NULL

_RESPONSE_REQUESTED = (
    "Set this parameter to false to ask the attendees for no response to the invitation."
)

RESPONSE_REQUESTED_FIELD = (
    _RESPONSE_REQUESTED
    + " Null sends nothing, and Microsoft then uses true, so each attendee is asked for a "
    + "response."
)

RESPONSE_REQUESTED_CHANGE_FIELD = _RESPONSE_REQUESTED + _KEPT_WHEN_NULL

_ALLOW_NEW_TIME_PROPOSALS = (
    "Set this parameter to false so that attendees cannot propose a new time when they respond."
)

ALLOW_NEW_TIME_PROPOSALS_FIELD = (
    _ALLOW_NEW_TIME_PROPOSALS
    + " Null sends nothing, and Microsoft then uses true, so attendees can propose a new time."
)

RECURRENCE_FIELD = (
    "Set this parameter to make the event repeat as a series. Null creates one event that does "
    + "not repeat. The series starts on the date of `starts_at` and uses `time_zone`. Give a "
    + "`starts_at` on a date that fits the pattern. Otherwise the first occurrence comes on a "
    + "later date."
)

SERIES_MASTER_FIELD = (
    "True when the event was the master of a recurring series, and false for a single event, an "
    + "occurrence, or an exception. Graph reports this in the `type` of the event."
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

_PREFER_HTML_BODY = ("Prefer", 'outlook.body-content-type="html"')

type PatternType = Literal[
    "daily", "weekly", "absoluteMonthly", "relativeMonthly", "absoluteYearly", "relativeYearly"
]

type DayName = Literal["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]

type WeekIndexName = Literal["first", "second", "third", "fourth", "last"]

type RangeType = Literal["endDate", "noEnd", "numbered"]

type ShowAs = Literal["free", "tentative", "busy", "oof", "workingElsewhere"]

type EventImportance = Literal["low", "normal", "high"]

type EventSensitivity = Literal["normal", "personal", "private", "confidential"]

_WEEK: tuple[DayName, ...] = (
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_PATTERN_NEEDS: Mapping[PatternType, tuple[str, ...]] = {
    "daily": (),
    "weekly": ("days_of_week",),
    "absoluteMonthly": ("day_of_month",),
    "relativeMonthly": ("days_of_week",),
    "absoluteYearly": ("day_of_month", "month"),
    "relativeYearly": ("days_of_week", "month"),
}

_UNITS: Mapping[PatternType, str] = {
    "daily": "day",
    "weekly": "week",
    "absoluteMonthly": "month",
    "relativeMonthly": "month",
    "absoluteYearly": "year",
    "relativeYearly": "year",
}

_PATTERN_ALSO_TAKES: Mapping[PatternType, tuple[str, ...]] = {
    "weekly": ("first_day_of_week",),
    "relativeMonthly": ("index",),
    "relativeYearly": ("index",),
}

_PATTERN_PARTS = ("days_of_week", "day_of_month", "month", "index", "first_day_of_week")

_RANGE_NEEDS: Mapping[RangeType, tuple[str, ...]] = {
    "endDate": ("end_date",),
    "numbered": ("number_of_occurrences",),
    "noEnd": (),
}

_RANGE_PARTS = ("end_date", "number_of_occurrences")

_SHOWN_AS: Mapping[ShowAs, str] = {
    "free": "free",
    "tentative": "tentative",
    "busy": "busy",
    "oof": "out of office",
    "workingElsewhere": "working elsewhere",
}


class RecurrencePatternSummary(BaseModel):
    kind: str | None = Field(
        description=(
            "How the series repeats: `daily`, `weekly`, `absoluteMonthly`, `relativeMonthly`, "
            + "`absoluteYearly`, or `relativeYearly`. An absolute pattern names a day of the "
            + "month. A relative pattern names a weekday and its position in the month. This "
            + "field is null when Graph did not say."
        )
    )
    interval: int | None = Field(
        description=(
            "The number of units between two occurrences. The unit is days for `daily`, weeks "
            + "for `weekly`, months for a monthly pattern, and years for a yearly pattern. For "
            + "example, 2 on a `weekly` pattern means every other week. This field is null when "
            + "Graph did not say."
        )
    )
    days_of_week: list[str] = Field(
        description=(
            "The weekdays on which the series occurs, in lowercase English, for example "
            + "`monday`. A `weekly` pattern and a relative pattern use this list. This list is "
            + "empty when Graph names no day."
        )
    )
    day_of_month: int | None = Field(
        description=(
            "The day of the month on which the series occurs. Only an `absoluteMonthly` or an "
            + "`absoluteYearly` pattern uses this value. This field is null when Graph did not "
            + "say."
        )
    )
    month: int | None = Field(
        description=(
            "The month in which the series occurs, as a number from 1 to 12. Only an "
            + "`absoluteYearly` or a `relativeYearly` pattern uses this value. This field is null "
            + "when Graph did not say."
        )
    )
    index: str | None = Field(
        description=(
            "The position in the month of the weekday that the series occurs on: `first`, "
            + "`second`, `third`, `fourth`, or `last`. Only a relative pattern uses this value. "
            + "This field is null when Graph did not say."
        )
    )
    first_day_of_week: str | None = Field(
        description=(
            "The day that Microsoft counts as the start of the week, in lowercase English, for "
            + "example `sunday`. Only a `weekly` pattern uses this value. This field is null when "
            + "Graph did not say."
        )
    )

    @classmethod
    def from_pattern(cls, pattern: RecurrencePattern) -> Self:
        days: Sequence[DayOfWeek | None] = pattern.days_of_week or []
        first = pattern.first_day_of_week
        return cls(
            kind=spelled(pattern.type),
            interval=pattern.interval,
            days_of_week=[spelled(day) for day in days if day is not None],
            day_of_month=pattern.day_of_month,
            month=pattern.month,
            index=spelled(pattern.index),
            first_day_of_week=spelled(first),
        )


class RecurrenceRangeSummary(BaseModel):
    kind: str | None = Field(
        description=(
            "How the series ends: `endDate` on a date, `numbered` after a set number of "
            + "occurrences, or `noEnd` for no end. This field is null when Graph did not say."
        )
    )
    start_date: str | None = Field(
        description=(
            "The date on which the pattern starts, as `YYYY-MM-DD`. The first occurrence is on "
            + "this date or later, as the pattern sets. This field is null when Graph did not say."
        )
    )
    end_date: str | None = Field(
        description=(
            "The last date on which the pattern applies, as `YYYY-MM-DD`. Only an `endDate` "
            + "range uses this value. The last occurrence can fall before this date. This field "
            + "is null when Graph did not say."
        )
    )
    number_of_occurrences: int | None = Field(
        description=(
            "How many times the series occurs. Only a `numbered` range uses this value. This "
            + "field is null when Graph did not say."
        )
    )
    recurrence_time_zone: str | None = Field(
        description=(
            "The zone for `start_date` and `end_date`, exactly as Graph wrote it. This field is "
            + "null when Graph named no zone. In that case, the zone of the event applies."
        )
    )

    @classmethod
    def from_range(cls, dates: RecurrenceRange) -> Self:
        return cls(
            kind=spelled(dates.type),
            start_date=None if dates.start_date is None else dates.start_date.isoformat(),
            end_date=None if dates.end_date is None else dates.end_date.isoformat(),
            number_of_occurrences=dates.number_of_occurrences,
            recurrence_time_zone=dates.recurrence_time_zone,
        )


class RecurrenceSummary(BaseModel):
    pattern: RecurrencePatternSummary | None = Field(
        description=(
            "How often the series repeats. Read `kind` first, because it decides which of the "
            + "other fields apply. This field is null when Graph returned no pattern."
        )
    )
    range: RecurrenceRangeSummary | None = Field(
        description=(
            "The dates over which the series repeats, and how the series ends. This field is "
            + "null when Graph returned no range."
        )
    )

    @classmethod
    def from_recurrence(cls, recurrence: PatternedRecurrence | None) -> Self | None:
        if recurrence is None:
            return None
        pattern = recurrence.pattern
        dates = recurrence.range
        return cls(
            pattern=None if pattern is None else RecurrencePatternSummary.from_pattern(pattern),
            range=None if dates is None else RecurrenceRangeSummary.from_range(dates),
        )


class RecurrenceRule(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    pattern_type: PatternType = Field(
        description=(
            "How the series repeats: `daily`, `weekly`, `absoluteMonthly`, `relativeMonthly`, "
            + "`absoluteYearly`, or `relativeYearly`. An absolute pattern names a day of the "
            + "month, for example the 15th. A relative pattern names a weekday and its position "
            + "in the month, for example the second Tuesday."
        )
    )
    interval: int = Field(
        default=1,
        ge=1,
        description=(
            "The number of units between two occurrences, 1 or more. The unit is days for "
            + "`daily`, weeks for `weekly`, months for a monthly pattern, and years for a yearly "
            + "pattern. For example, 2 on a `weekly` pattern means every other week."
        ),
    )
    days_of_week: tuple[DayName, ...] = Field(
        default=(),
        description=(
            "The weekdays on which the series occurs, in lowercase English, for example "
            + "`monday`. A `weekly`, `relativeMonthly`, or `relativeYearly` pattern needs one or "
            + "more days, and the other patterns take none. A relative pattern with two or more "
            + "days falls on the first day that fits."
        ),
    )
    day_of_month: int | None = Field(
        default=None,
        ge=1,
        le=31,
        description=(
            "The day of the month on which the series occurs, from 1 to 31. An "
            + "`absoluteMonthly` or an `absoluteYearly` pattern needs this value, and the other "
            + "patterns take none."
        ),
    )
    month: int | None = Field(
        default=None,
        ge=1,
        le=12,
        description=(
            "The month in which the series occurs, as a number from 1 to 12. An "
            + "`absoluteYearly` or a `relativeYearly` pattern needs this value, and the other "
            + "patterns take none."
        ),
    )
    index: WeekIndexName | None = Field(
        default=None,
        description=(
            "The position in the month of the weekday that the series occurs on: `first`, "
            + "`second`, `third`, `fourth`, or `last`. Only a relative pattern takes this value. "
            + "Null sends nothing, and Microsoft then uses `first`."
        ),
    )
    first_day_of_week: DayName | None = Field(
        default=None,
        description=(
            "The day that Microsoft counts as the start of the week, in lowercase English. Only a "
            + "`weekly` pattern takes this value. Null sends nothing, and Microsoft then uses "
            + "`sunday`."
        ),
    )
    range_type: RangeType = Field(
        description=(
            "How the series ends: `endDate` on the date in `end_date`, `numbered` after the "
            + "count in `number_of_occurrences`, or `noEnd` with no end."
        )
    )
    end_date: date | None = Field(
        default=None,
        description=(
            "The last date on which the series can occur, as `YYYY-MM-DD`, on or after the date "
            + "of `starts_at`. An `endDate` range needs this value, and the other ranges take "
            + "none. The last occurrence can fall before this date."
        ),
    )
    number_of_occurrences: int | None = Field(
        default=None,
        ge=1,
        description=(
            "How many times the series occurs, 1 or more. A `numbered` range needs this value, "
            + "and the other ranges take none."
        ),
    )

    @field_validator("days_of_week")
    @classmethod
    def _in_week_order(cls, days: tuple[DayName, ...]) -> tuple[DayName, ...]:
        return tuple(day for day in _WEEK if day in days)


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
            default_online_meeting_provider=spelled(calendar.default_online_meeting_provider),
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
            kind=spelled(attendee.type),
            response=spelled(None if status is None else status.response),
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
        description=(
            "The row kind, as Microsoft spells it: `singleInstance`, `occurrence`, "
            + "`exception`, or `seriesMaster`. outlook_read_event returns `seriesMaster` when it "
            + "reads the series master that a `series_master_uri` names. This field is null if "
            + "unknown."
        )
    )
    in_series: bool = Field(
        description=(
            "Whether this row belongs to a recurring series. This is true for an occurrence, an "
            + "exception, and the series master. It is false for a single event."
        )
    )
    series_master_uri: str | None = Field(
        description=(
            "A handle for the series master of the recurring series of this row, in the same "
            + "shape as `uri`. outlook_read_event reads the master from this handle "
            + "and returns the recurrence rule. This field is null when Graph names no series "
            + "master, as on a single event and on the series master itself."
        )
    )
    sensitivity: str | None = Field(
        description="How the owner classified the event, or null if unknown."
    )
    show_as: str | None = Field(
        description="How the event shows in the owner's free-busy view, or null if unknown."
    )
    categories: list[str] = Field(description=STORED_CATEGORIES_FIELD)
    importance: str | None = Field(description=STORED_IMPORTANCE_FIELD)
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
        master = event.series_master_id
        return cls(
            uri=EventHandle(calendar_id, event.id).uri,
            subject=event.subject,
            preview=event.body_preview,
            start=event_time(event.start, zone=zone),
            end=event_time(event.end, zone=zone),
            all_day=event.is_all_day,
            cancelled=event.is_cancelled,
            kind=spelled(event.type),
            in_series=master is not None or event.type == EventType.SeriesMaster,
            series_master_uri=None if master is None else EventHandle(calendar_id, master).uri,
            sensitivity=spelled(event.sensitivity),
            show_as=spelled(event.show_as),
            categories=list(event.categories or []),
            importance=spelled(event.importance),
            location=None if event.location is None else event.location.display_name,
            is_online_meeting=event.is_online_meeting,
            join_url=None if online is None else online.join_url,
            organizer=MailAddress.from_recipient(event.organizer),
            owner_is_organizer=event.is_organizer,
            owner_response=spelled(None if status is None else status.response),
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


async def event_of(
    client: GraphServiceClient,
    *,
    calendar_id: str,
    event_id: str,
    also: tuple[str, ...] = (),
    html_body: bool = False,
) -> Event:
    headers = immutable_id_headers()
    if html_body:
        headers.add(*_PREFER_HTML_BODY)
    with graph_step(STEP_EVENT):
        found = (
            await client.me.calendars.by_calendar_id(calendar_id)
            .events.by_event_id(event_id)
            .get(
                request_configuration=RequestConfiguration[_EventItemQuery](
                    query_parameters=_EventItemQuery(
                        select=[*SUMMARY_FIELDS, *also, *(("body",) if html_body else ())]
                    ),
                    headers=headers,
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
    recurrence: RecurrenceRule | None = None


def recurrence_refusal(tool: str, rule: RecurrenceRule | None, *, starts_on: date) -> str | None:
    problem = None if rule is None else _rule_problem(rule, starts_on=starts_on)
    if problem is None:
        return None
    return (
        f"{tool} cannot send this `recurrence`. {problem} NO EVENT WAS CREATED and nobody was "
        + "invited. If you call this tool again with the same arguments, the call will fail the "
        + "same way."
    )


def _rule_problem(rule: RecurrenceRule, *, starts_on: date) -> str | None:
    dumped = cast("Mapping[str, object]", rule.model_dump(exclude_none=True))
    given = {name for name, value in dumped.items() if value != ()}
    needs = _PATTERN_NEEDS[rule.pattern_type]
    ends_with = _RANGE_NEEDS[rule.range_type]
    for owner, wanted, taken, parts in (
        (
            f"The `{rule.pattern_type}` pattern",
            needs,
            (*needs, *_PATTERN_ALSO_TAKES.get(rule.pattern_type, ())),
            _PATTERN_PARTS,
        ),
        (f"The `{rule.range_type}` range", ends_with, ends_with, _RANGE_PARTS),
    ):
        missing = [name for name in wanted if name not in given]
        if missing:
            return f"{owner} needs {_named(missing)}. Add {_named(missing)} to `recurrence`."
        extra = [name for name in parts if name in given and name not in taken]
        if extra:
            return f"{owner} takes no {_named(extra)}. Remove {_named(extra)} from `recurrence`."
    if rule.end_date is not None and rule.end_date < starts_on:
        return (
            f"The `end_date` {rule.end_date} is before {starts_on}, the date of `starts_at`. Give "
            + f"an `end_date` on or after {starts_on}."
        )
    return None


def _named(names: Sequence[str]) -> str:
    return " and ".join(f"`{name}`" for name in names)


def draft_details(draft: EventDraft) -> str:
    return ", ".join(
        detail
        for detail in (
            _whole_days(draft) if draft.all_day else "",
            "" if draft.recurrence is None else _repeats(draft.recurrence),
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
    before = _before_the_start(minutes)
    if on is False:
        return f"with no reminder, and a reminder time of {before}"
    return f"with a reminder {before}"


def _before_the_start(minutes: int) -> str:
    return f"{minutes} {'minute' if minutes == 1 else 'minutes'} before the start"


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


def _repeats(rule: RecurrenceRule) -> str:
    return f"repeating {_how_often(rule)}{_until(rule)}"


def _how_often(rule: RecurrenceRule) -> str:
    unit = _UNITS[rule.pattern_type]
    every = f"every {unit}" if rule.interval == 1 else f"every {rule.interval} {unit}s"
    relative = f"the {rule.index or 'first'} {_days(rule.days_of_week, 'or')}"
    match rule.pattern_type:
        case "daily":
            return every
        case "weekly":
            week = (
                ""
                if rule.first_day_of_week is None
                else f" (weeks start on {rule.first_day_of_week.title()})"
            )
            return f"{every} on {_days(rule.days_of_week, 'and')}{week}"
        case "absoluteMonthly":
            return f"{every} on day {rule.day_of_month}"
        case "relativeMonthly":
            return f"{every} on {relative}"
        case "absoluteYearly":
            return f"{every} on {_month(rule.month)} {rule.day_of_month}"
        case "relativeYearly":
            return f"{every} on {relative} of {_month(rule.month)}"


def _until(rule: RecurrenceRule) -> str:
    match rule.range_type:
        case "numbered":
            count = rule.number_of_occurrences
            return f", {count} {'time' if count == 1 else 'times'}"
        case "endDate":
            return f" until {rule.end_date}"
        case "noEnd":
            return " with no end"


def _days(days: Sequence[DayName], joiner: str) -> str:
    named = [day.title() for day in days]
    if len(named) <= 2:
        return f" {joiner} ".join(named)
    return f"{', '.join(named[:-1])}, {joiner} {named[-1]}"


def _month(month: int | None) -> str:
    assert month is not None, "a yearly rule names its month before a draft holds it"
    return _MONTHS[month - 1]


def _first_day(draft: EventDraft) -> date:
    opens = wall_clock(draft.starts_at)
    assert opens is not None, (
        "a draft holds a start that the create already read as a wall-clock time"
    )
    return opens.date()


def _patterned(rule: RecurrenceRule, *, starts_on: date) -> PatternedRecurrence:
    return PatternedRecurrence(
        pattern=RecurrencePattern(
            type=RecurrencePatternType(rule.pattern_type),
            interval=rule.interval,
            days_of_week=[DayOfWeek(day) for day in rule.days_of_week] or None,
            day_of_month=rule.day_of_month,
            month=rule.month,
            index=None if rule.index is None else WeekIndex(rule.index),
            first_day_of_week=(
                None if rule.first_day_of_week is None else DayOfWeek(rule.first_day_of_week)
            ),
        ),
        range=RecurrenceRange(
            type=RecurrenceRangeType(rule.range_type),
            start_date=starts_on,
            end_date=rule.end_date,
            number_of_occurrences=rule.number_of_occurrences,
        ),
    )


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
        recurrence=(
            None
            if draft.recurrence is None
            else _patterned(draft.recurrence, starts_on=_first_day(draft))
        ),
        transaction_id=transaction_id,
    )


@dataclass(frozen=True, slots=True)
class EventPatch:
    subject: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    time_zone: str | None = None
    location: str | None = None
    attendees: tuple[str, ...] | None = None
    optional_attendees: tuple[str, ...] | None = None
    show_as: ShowAs | None = None
    categories: tuple[str, ...] | None = None
    importance: EventImportance | None = None
    sensitivity: EventSensitivity | None = None
    is_reminder_on: bool | None = None
    reminder_minutes_before_start: int | None = None
    hide_attendees: bool | None = None
    response_requested: bool | None = None
    body_html: str | None = None
    online_meeting: bool = False


def patch_changes(patch: EventPatch) -> list[str]:
    return [
        change
        for change in (
            "" if patch.subject is None else f"change the subject to {patch.subject!r}",
            (
                ""
                if patch.starts_at is None
                else f"change the time to {patch.starts_at} – {patch.ends_at} {patch.time_zone}"
            ),
            "" if patch.location is None else f"change the location to {patch.location!r}",
            "" if patch.show_as is None else f"show it as {_SHOWN_AS[patch.show_as]}",
            _categories_set(patch.categories),
            "" if patch.importance is None else f"set the importance to {patch.importance}",
            "" if patch.sensitivity is None else f"set the sensitivity to {patch.sensitivity}",
            _either(patch.is_reminder_on, yes="set a reminder", no="remove the reminder"),
            (
                ""
                if patch.reminder_minutes_before_start is None
                else "set the reminder time to "
                + _before_the_start(patch.reminder_minutes_before_start)
            ),
            _either(
                patch.hide_attendees,
                yes="hide the attendee list",
                no="show the attendee list to every attendee",
            ),
            _either(
                patch.response_requested,
                yes="ask the attendees for a response",
                no="ask the attendees for no response",
            ),
            (
                ""
                if patch.body_html is None
                else f"replace the body {_body_described(patch.body_html)}"
            ),
            (
                "add a Teams meeting that this connector cannot remove later"
                if patch.online_meeting
                else ""
            ),
            _attendee_list_set(patch),
        )
        if change
    ]


def _categories_set(categories: tuple[str, ...] | None) -> str:
    if categories is None:
        return ""
    if not categories:
        return "remove every category"
    return f"set the categories to {cut_for_a_question(', '.join(categories))!r}"


def _attendee_list_set(patch: EventPatch) -> str:
    if patch.attendees is None:
        return ""
    invited = [*patch.attendees, *(f"{one} (optional)" for one in patch.optional_attendees or ())]
    if not invited:
        return "change the attendee list to nobody"
    return f"change the attendee list to {counted_people(invited)}: {', '.join(invited)}"


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
        show_as=None if patch.show_as is None else FreeBusyStatus(patch.show_as),
        categories=None if patch.categories is None else list(patch.categories),
        importance=None if patch.importance is None else Importance(patch.importance),
        sensitivity=None if patch.sensitivity is None else Sensitivity(patch.sensitivity),
        is_reminder_on=patch.is_reminder_on,
        reminder_minutes_before_start=patch.reminder_minutes_before_start,
        hide_attendees=patch.hide_attendees,
        response_requested=patch.response_requested,
        body=(
            None
            if patch.body_html is None
            else ItemBody(content=patch.body_html, content_type=BodyType.Html)
        ),
        is_online_meeting=True if patch.online_meeting else None,
        online_meeting_provider=(
            OnlineMeetingProviderType.TeamsForBusiness if patch.online_meeting else None
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
        *_rule_spelled(draft.recurrence),
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


def _rule_spelled(rule: RecurrenceRule | None) -> list[str]:
    return [] if rule is None else [rule.model_dump_json()]


def series_reach(event: Event, *, what: str) -> str:
    if event.type == EventType.SeriesMaster:
        return f"The {what} applies to every occurrence of the series."
    if event.type in (EventType.Occurrence, EventType.Exception):
        return (
            f"The {what} applies only to this one date. The other occurrences of the series stay "
            + "as they are."
        )
    return ""


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
