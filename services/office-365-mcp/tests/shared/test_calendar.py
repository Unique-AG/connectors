"""The shared calendar vocabulary: the times, the two rows, the create body and the two predicates.

Time is most of this file. Graph states an event's bounds as a naive string plus a zone name, and
renders them in UTC when nothing asks otherwise, so every wrong answer about a meeting is a wrong
answer about hours. The assertions below pin the conversion, the zone names that resolve, the one
that does not, and the two window bounds that carry their own offset.

The create body is the other half. What kiota leaves out of the payload is what Microsoft is told
nothing about, so the assertions read the serialized JSON rather than the object.

Every payload here is invented. No id, address or subject came from a real mailbox.
"""

import json
import uuid
from datetime import UTC, date, datetime
from typing import cast
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from kiota_serialization_json.json_serialization_writer import JsonSerializationWriter
from msgraph.generated.models.attendee import Attendee
from msgraph.generated.models.attendee_type import AttendeeType
from msgraph.generated.models.calendar import Calendar
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.event import Event
from msgraph.generated.models.event_type import EventType
from msgraph.generated.models.free_busy_status import FreeBusyStatus
from msgraph.generated.models.location import Location
from msgraph.generated.models.online_meeting_info import OnlineMeetingInfo
from msgraph.generated.models.online_meeting_provider_type import OnlineMeetingProviderType
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.response_status import ResponseStatus
from msgraph.generated.models.response_type import ResponseType
from msgraph.generated.models.sensitivity import Sensitivity
from msgraph.generated.models.user import User
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared.calendar import (
    CALENDAR_FIELDS,
    CalendarSummary,
    EventAttendee,
    EventDraft,
    EventSummary,
    calendar_of,
    event_body,
    event_time,
    person_matches,
    subject_matches,
    transaction_id_for,
    window_bounds,
    zone_named,
)
from office_365_mcp.shared.handles import CalendarHandle, EventHandle

_UTC = ZoneInfo("UTC")
_ZURICH = ZoneInfo("Europe/Zurich")

# A Windows zone name. Graph accepts and returns these, and `zoneinfo` has no such key.
_WINDOWS_ZONE = "W. Europe Standard Time"

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0001="
_EVENT_ID = "AAMkAGI2SYNTHETIC-immutable-0001="

_MINE = "ada@example.invalid"
_MY_UPN = "ada@corp.example.invalid"
_SOMEBODY_ELSE = "alex@example.invalid"

_SIGNED_IN = User(
    id="00000000-0000-4000-8000-000000000001", mail=_MINE, user_principal_name=_MY_UPN
)


def _draft(
    *,
    subject: str = "Pricing review",
    starts_at: str = "2026-03-02T14:00",
    ends_at: str = "2026-03-02T15:00",
    time_zone: str = "UTC",
    attendees: tuple[str, ...] = (),
    optional_attendees: tuple[str, ...] = (),
    body_html: str | None = None,
    location: str | None = None,
    all_day: bool = False,
    online_meeting: bool = False,
) -> EventDraft:
    return EventDraft(
        subject=subject,
        starts_at=starts_at,
        ends_at=ends_at,
        time_zone=time_zone,
        attendees=attendees,
        optional_attendees=optional_attendees,
        body_html=body_html,
        location=location,
        all_day=all_day,
        online_meeting=online_meeting,
    )


def _payload(event: Event) -> dict[str, object]:
    """The JSON kiota puts on the wire for this event. An unset property is absent here, and that
    is the difference between telling Microsoft nothing and telling it nothing is there."""
    writer = JsonSerializationWriter()
    event.serialize(writer)
    return cast("dict[str, object]", json.loads(writer.get_serialized_content()))


def _calendar_payload(
    *,
    calendar_id: str = _CALENDAR_ID,
    name: str | None = "Calendar",
    owner: str | None = _MINE,
) -> dict[str, object]:
    return {
        "id": calendar_id,
        "name": name,
        "owner": None if owner is None else {"name": "Ada Lovelace", "address": owner},
        "canEdit": True,
        "canShare": True,
        "canViewPrivateItems": True,
        "isDefaultCalendar": True,
        "isTallyingResponses": True,
        "allowedOnlineMeetingProviders": ["teamsForBusiness"],
        "defaultOnlineMeetingProvider": "teamsForBusiness",
    }


class TestHowAnInstantIsReported:
    def test_it_reads_the_seven_fractional_digits_graph_writes(self) -> None:
        """`2026-09-07T13:00:00.0000000` is Graph's own shape, with one digit more than a
        microsecond has room for."""
        moment = event_time(
            DateTimeTimeZone(date_time="2026-09-07T13:00:00.0000000", time_zone="UTC"), zone=_UTC
        )

        assert moment is not None
        assert moment.local == "2026-09-07T13:00:00.0000000", "Graph's own string, verbatim"
        assert moment.iso == "2026-09-07T13:00:00+00:00"

    def test_it_converts_utc_into_the_zone_that_was_asked_for(self) -> None:
        moment = event_time(
            DateTimeTimeZone(date_time="2026-07-06T13:00:00.0000000", time_zone="UTC"),
            zone=_ZURICH,
        )

        assert moment is not None
        assert moment.iso == "2026-07-06T15:00:00+02:00"
        assert moment.time_zone == "UTC", "what Graph said, beside what it means"

    @pytest.mark.parametrize(
        ("utc", "expected"),
        [
            ("2026-10-25T00:30:00.0000000", "2026-10-25T02:30:00+02:00"),
            ("2026-10-25T01:30:00.0000000", "2026-10-25T02:30:00+01:00"),
        ],
        ids=["before-the-change", "after-the-change"],
    )
    def test_it_converts_across_a_daylight_saving_boundary(self, utc: str, expected: str) -> None:
        """Two instants an hour apart, both `02:30` in Zurich on the morning the clocks go back.
        Only the offset tells them apart, which is why the offset is in the reported value."""
        moment = event_time(DateTimeTimeZone(date_time=utc, time_zone="UTC"), zone=_ZURICH)

        assert moment is not None and moment.iso == expected

    def test_a_windows_zone_name_leaves_the_comparable_value_null(self) -> None:
        """Graph returns the zone the event was created with, and Outlook creates events with
        Windows zone names. Both of Graph's own values still answer the question."""
        moment = event_time(
            DateTimeTimeZone(date_time="2026-03-02T14:00:00.0000000", time_zone=_WINDOWS_ZONE),
            zone=_ZURICH,
        )

        assert moment is not None
        assert moment.iso is None
        assert moment.local == "2026-03-02T14:00:00.0000000"
        assert moment.time_zone == _WINDOWS_ZONE

    def test_a_zone_graph_named_none_for_leaves_it_null_too(self) -> None:
        moment = event_time(DateTimeTimeZone(date_time="2026-03-02T14:00:00"), zone=_UTC)

        assert moment is not None and moment.iso is None

    def test_a_local_time_that_is_not_a_timestamp_leaves_it_null(self) -> None:
        """A refusal rather than a raise: one unreadable bound must not lose the whole listing."""
        moment = event_time(DateTimeTimeZone(date_time="soon", time_zone="UTC"), zone=_UTC)

        assert moment is not None and moment.iso is None and moment.local == "soon"

    @pytest.mark.parametrize(
        "moment",
        [None, DateTimeTimeZone(), DateTimeTimeZone(time_zone="UTC")],
        ids=["no-bound", "empty-bound", "zone-only"],
    )
    def test_no_stated_time_is_no_time(self, moment: DateTimeTimeZone | None) -> None:
        assert event_time(moment, zone=_UTC) is None


class TestWhichZoneNamesResolve:
    @pytest.mark.parametrize("name", ["UTC", "Europe/Zurich", "America/New_York", "Etc/GMT+2"])
    def test_utc_and_every_iana_name_resolve(self, name: str) -> None:
        zone = zone_named(name)

        assert zone is not None and str(zone) == name

    @pytest.mark.parametrize(
        "name",
        [_WINDOWS_ZONE, "Pacific Standard Time", "", "   ", "/etc/localtime", "../etc/localtime"],
        ids=["windows", "windows-pacific", "empty", "blank", "absolute", "escaping"],
    )
    def test_everything_else_is_refused_rather_than_raised(self, name: str) -> None:
        """An unknown key and a key that is not a normalized relative path raise two different
        exceptions, and a tool needs one answer for both."""
        assert zone_named(name) is None


class TestTheWindowBounds:
    def test_both_bounds_carry_the_offset_of_the_zone_that_was_asked_for(self) -> None:
        opens, closes = window_bounds(date(2026, 7, 6), date(2026, 7, 6), zone=_ZURICH)

        assert opens == "2026-07-06T00:00:00+02:00"
        assert closes == "2026-07-07T00:00:00+02:00"

    def test_the_end_bound_is_the_midnight_after_the_last_day(self) -> None:
        """Graph reads the bounds as instants, so an end bound of midnight ON the last day would
        drop that whole day."""
        _, closes = window_bounds(date(2026, 3, 2), date(2026, 3, 8), zone=_UTC)

        assert closes == "2026-03-09T00:00:00+00:00"

    def test_utc_renders_a_zero_offset_and_never_a_bare_time(self) -> None:
        """Graph reads a bound with no offset as UTC, so a bare time is only ever right by
        accident."""
        opens, closes = window_bounds(date(2026, 3, 2), date(2026, 3, 2), zone=_UTC)

        assert opens == "2026-03-02T00:00:00+00:00"
        assert closes == "2026-03-03T00:00:00+00:00"

    def test_a_window_of_one_date_holds_that_whole_day(self) -> None:
        opens, closes = window_bounds(date(2026, 7, 6), date(2026, 7, 6), zone=_ZURICH)

        span = datetime.fromisoformat(closes) - datetime.fromisoformat(opens)

        assert span.total_seconds() == 24 * 60 * 60


class TestOneCalendarRow:
    def test_it_mints_the_handle_every_other_calendar_tool_takes(self) -> None:
        row = CalendarSummary.from_calendar(Calendar(id=_CALENDAR_ID), signed_in=None)

        assert row.uri == CalendarHandle(_CALENDAR_ID).uri

    @pytest.mark.parametrize("owner", [_MINE, _MY_UPN, _MINE.upper()])
    def test_a_calendar_the_signed_in_user_owns_is_theirs(self, owner: str) -> None:
        """Graph gives a user two addresses and states an owner with either one, and SMTP
        addresses are not case-sensitive."""
        calendar = Calendar(id=_CALENDAR_ID, owner=EmailAddress(address=owner))

        row = CalendarSummary.from_calendar(calendar, signed_in=_SIGNED_IN)

        assert row.is_mine is True

    def test_a_delegated_calendar_is_somebody_elses(self) -> None:
        """This is the only property that says so: `isSharedWithMe` does not exist on `calendar`
        in v1.0."""
        calendar = Calendar(
            id=_CALENDAR_ID,
            name="Alex Wilber",
            owner=EmailAddress(name="Alex Wilber", address=_SOMEBODY_ELSE),
            can_edit=True,
            can_share=False,
            can_view_private_items=False,
        )

        row = CalendarSummary.from_calendar(calendar, signed_in=_SIGNED_IN)

        assert row.is_mine is False
        assert row.can_edit is True
        assert row.can_view_private_items is False
        assert row.owner is not None and row.owner.address == _SOMEBODY_ELSE

    @pytest.mark.parametrize(
        "calendar",
        [Calendar(id=_CALENDAR_ID), Calendar(id=_CALENDAR_ID, owner=EmailAddress())],
        ids=["no-owner", "owner-without-an-address"],
    )
    def test_an_owner_graph_did_not_state_is_unknown_and_not_somebody_else(
        self, calendar: Calendar
    ) -> None:
        assert CalendarSummary.from_calendar(calendar, signed_in=_SIGNED_IN).is_mine is None

    def test_a_tool_that_read_no_signed_in_user_says_it_does_not_know(self) -> None:
        calendar = Calendar(id=_CALENDAR_ID, owner=EmailAddress(address=_MINE))

        assert CalendarSummary.from_calendar(calendar, signed_in=None).is_mine is None

    def test_the_meeting_providers_come_back_in_microsofts_own_spelling(self) -> None:
        calendar = Calendar(
            id=_CALENDAR_ID,
            allowed_online_meeting_providers=[
                OnlineMeetingProviderType.TeamsForBusiness,
                OnlineMeetingProviderType.SkypeForBusiness,
            ],
            default_online_meeting_provider=OnlineMeetingProviderType.TeamsForBusiness,
        )

        row = CalendarSummary.from_calendar(calendar, signed_in=None)

        assert row.online_meeting_providers == ["teamsForBusiness", "skypeForBusiness"]
        assert row.default_online_meeting_provider == "teamsForBusiness"


class TestOneEventRow:
    def test_it_mints_a_handle_carrying_the_calendar_it_was_read_from(self) -> None:
        """Graph puts no calendar id on an event, and the reader's route needs one."""
        row = EventSummary.from_event(Event(id=_EVENT_ID), calendar_id=_CALENDAR_ID, zone=_UTC)

        assert row.uri == EventHandle(_CALENDAR_ID, _EVENT_ID).uri

    def test_it_reports_the_calendar_owners_response_verbatim_including_none(self) -> None:
        """`none` is Microsoft's own spelling and the SDK's member is `None_`, so a row that
        answered `null` here would read as "Graph did not say"."""
        event = Event(id=_EVENT_ID, response_status=ResponseStatus(response=ResponseType.None_))

        row = EventSummary.from_event(event, calendar_id=_CALENDAR_ID, zone=_UTC)

        assert row.owner_response == "none"

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            (ResponseType.Organizer, "organizer"),
            (ResponseType.TentativelyAccepted, "tentativelyAccepted"),
            (ResponseType.NotResponded, "notResponded"),
            (ResponseType.Declined, "declined"),
        ],
    )
    def test_every_other_response_is_microsofts_spelling_too(
        self, response: ResponseType, expected: str
    ) -> None:
        event = Event(id=_EVENT_ID, response_status=ResponseStatus(response=response))

        row = EventSummary.from_event(event, calendar_id=_CALENDAR_ID, zone=_UTC)

        assert row.owner_response == expected

    def test_the_other_enums_are_microsofts_spelling_as_well(self) -> None:
        event = Event(
            id=_EVENT_ID,
            type=EventType.Occurrence,
            sensitivity=Sensitivity.Private,
            show_as=FreeBusyStatus.WorkingElsewhere,
        )

        row = EventSummary.from_event(event, calendar_id=_CALENDAR_ID, zone=_UTC)

        assert (row.kind, row.sensitivity, row.show_as) == (
            "occurrence",
            "private",
            "workingElsewhere",
        )

    def test_one_date_of_a_recurring_series_says_it_belongs_to_one(self) -> None:
        """`calendarView` answers with occurrences, so a weekly meeting is one row per week."""
        event = Event(id=_EVENT_ID, type=EventType.Occurrence, series_master_id="AAMkSYNTHETIC-m1=")

        row = EventSummary.from_event(event, calendar_id=_CALENDAR_ID, zone=_UTC)

        assert row.in_series is True

    def test_a_single_meeting_belongs_to_no_series(self) -> None:
        event = Event(id=_EVENT_ID, type=EventType.SingleInstance)

        assert not EventSummary.from_event(event, calendar_id=_CALENDAR_ID, zone=_UTC).in_series

    def test_the_join_link_comes_from_the_online_meeting_and_not_the_deprecated_property(
        self,
    ) -> None:
        """Microsoft deprecated `onlineMeetingUrl` and documents `onlineMeeting.joinUrl` as its
        replacement, and the deprecated one is empty on events created since."""
        event = Event(
            id=_EVENT_ID,
            is_online_meeting=True,
            online_meeting=OnlineMeetingInfo(join_url="https://teams.microsoft.invalid/l/join/1"),
            online_meeting_url="https://teams.microsoft.invalid/l/deprecated/1",
        )

        row = EventSummary.from_event(event, calendar_id=_CALENDAR_ID, zone=_UTC)

        assert row.join_url == "https://teams.microsoft.invalid/l/join/1"

    def test_attendees_are_counted_here_and_never_listed(self) -> None:
        """A listing selects attendees for the person match and reports the count, because
        twenty-five rows of full attendee lists is a page nobody asked for."""
        event = Event(
            id=_EVENT_ID,
            attendees=[
                Attendee(email_address=EmailAddress(address=_MINE)),
                Attendee(email_address=EmailAddress(address=_SOMEBODY_ELSE)),
            ],
        )

        row = EventSummary.from_event(event, calendar_id=_CALENDAR_ID, zone=_UTC)

        assert row.attendee_count == 2

    def test_an_event_nobody_was_invited_to_counts_none(self) -> None:
        row = EventSummary.from_event(Event(id=_EVENT_ID), calendar_id=_CALENDAR_ID, zone=_UTC)

        assert row.attendee_count == 0

    def test_it_converts_both_bounds_into_the_zone_that_was_asked_for(self) -> None:
        event = Event(
            id=_EVENT_ID,
            start=DateTimeTimeZone(date_time="2026-07-06T13:00:00.0000000", time_zone="UTC"),
            end=DateTimeTimeZone(date_time="2026-07-06T14:00:00.0000000", time_zone="UTC"),
        )

        row = EventSummary.from_event(event, calendar_id=_CALENDAR_ID, zone=_ZURICH)

        assert row.start is not None and row.start.iso == "2026-07-06T15:00:00+02:00"
        assert row.end is not None and row.end.iso == "2026-07-06T16:00:00+02:00"

    def test_the_location_is_one_line_of_whatever_somebody_typed(self) -> None:
        event = Event(id=_EVENT_ID, location=Location(display_name="Zurich HQ, room 4"))

        row = EventSummary.from_event(event, calendar_id=_CALENDAR_ID, zone=_UTC)

        assert row.location == "Zurich HQ, room 4"


class TestOneAttendee:
    def test_it_reports_the_kind_and_the_answer_in_microsofts_spelling(self) -> None:
        attendee = Attendee(
            email_address=EmailAddress(name="Alex Wilber", address=_SOMEBODY_ELSE),
            type=AttendeeType.Optional,
            status=ResponseStatus(
                response=ResponseType.Accepted,
                time=datetime(2026, 3, 1, 9, 15, tzinfo=UTC),
            ),
        )

        one = EventAttendee.from_attendee(attendee)

        assert (one.name, one.address, one.kind, one.response) == (
            "Alex Wilber",
            _SOMEBODY_ELSE,
            "optional",
            "accepted",
        )
        assert one.responded_at == "2026-03-01T09:15:00+00:00"

    def test_a_room_is_reported_as_the_resource_it_is(self) -> None:
        """Exchange adds a resource attendee of its own when a location matches a bookable room,
        which is why an answer reports the attendees Graph stored rather than the arguments."""
        attendee = Attendee(
            email_address=EmailAddress(address="room4@example.invalid"), type=AttendeeType.Resource
        )

        assert EventAttendee.from_attendee(attendee).kind == "resource"

    def test_an_unanswered_invitation_carries_no_timestamp(self) -> None:
        """Graph fills `0001-01-01T00:00:00Z` in for nobody having answered, and reporting that
        year reads as a response from before the calendar existed."""
        attendee = Attendee(
            email_address=EmailAddress(address=_SOMEBODY_ELSE),
            status=ResponseStatus(
                response=ResponseType.NotResponded, time=datetime(1, 1, 1, tzinfo=UTC)
            ),
        )

        one = EventAttendee.from_attendee(attendee)

        assert one.response == "notResponded"
        assert one.responded_at is None

    def test_an_attendee_graph_said_nothing_about_is_all_nulls(self) -> None:
        one = EventAttendee.from_attendee(Attendee())

        assert (one.name, one.address, one.kind, one.response, one.responded_at) == (
            None,
            None,
            None,
            None,
            None,
        )

    def test_a_list_graph_did_not_send_is_no_attendees(self) -> None:
        assert EventAttendee.each_of(None) == []


class TestTheCreateBody:
    def test_it_omits_everything_the_draft_did_not_name(self) -> None:
        """An absent key is Microsoft being told nothing. `attendees: []` would be Microsoft being
        told there are no attendees, which is a different request."""
        body = _payload(event_body(_draft(), transaction_id="synthetic-transaction"))

        assert "body" not in body
        assert "location" not in body
        assert "attendees" not in body

    @pytest.mark.parametrize(
        "property_name",
        [
            "hideAttendees",
            "recurrence",
            "responseRequested",
            "allowNewTimeProposals",
            "attachments",
        ],
    )
    def test_it_never_names_a_property_no_tool_here_offers(self, property_name: str) -> None:
        draft = _draft(
            attendees=(_SOMEBODY_ELSE,),
            body_html="<p>Agenda attached.</p>",
            location="Zurich HQ",
            online_meeting=True,
        )

        body = _payload(event_body(draft, transaction_id="synthetic-transaction"))

        assert property_name not in body

    def test_the_subject_the_bounds_and_the_transaction_id_are_always_sent(self) -> None:
        body = _payload(event_body(_draft(), transaction_id="synthetic-transaction"))

        assert body["subject"] == "Pricing review"
        assert body["start"] == {"dateTime": "2026-03-02T14:00", "timeZone": "UTC"}
        assert body["end"] == {"dateTime": "2026-03-02T15:00", "timeZone": "UTC"}
        assert body["isAllDay"] is False
        assert body["transactionId"] == "synthetic-transaction"

    def test_the_zone_goes_on_the_wire_exactly_as_the_caller_gave_it(self) -> None:
        """Graph accepts a Windows or an IANA name here, and translating one would change which
        instant the event is at."""
        body = _payload(
            event_body(_draft(time_zone=_WINDOWS_ZONE), transaction_id="synthetic-transaction")
        )

        assert body["start"] == {"dateTime": "2026-03-02T14:00", "timeZone": _WINDOWS_ZONE}

    def test_required_and_optional_attendees_carry_microsofts_own_type(self) -> None:
        draft = _draft(attendees=(_SOMEBODY_ELSE,), optional_attendees=("sam@example.invalid",))

        body = _payload(event_body(draft, transaction_id="synthetic-transaction"))

        assert body["attendees"] == [
            {
                "emailAddress": {"address": _SOMEBODY_ELSE},
                "@odata.type": "#microsoft.graph.attendee",
                "type": "required",
            },
            {
                "emailAddress": {"address": "sam@example.invalid"},
                "@odata.type": "#microsoft.graph.attendee",
                "type": "optional",
            },
        ]

    def test_the_body_is_sent_as_html_and_only_as_html(self) -> None:
        body = _payload(
            event_body(_draft(body_html="<p>Agenda attached.</p>"), transaction_id="synthetic")
        )

        assert body["body"] == {"content": "<p>Agenda attached.</p>", "contentType": "html"}

    def test_a_location_is_sent_as_a_display_name_and_nothing_else(self) -> None:
        """A `locationEmailAddress` can make Exchange book a room and add a resource attendee, so
        no tool here sends one."""
        body = _payload(event_body(_draft(location="Zurich HQ"), transaction_id="synthetic"))

        assert body["location"] == {"displayName": "Zurich HQ"}

    def test_an_online_meeting_names_teams_and_nothing_else_does(self) -> None:
        """Microsoft documents that `isOnlineMeeting` cannot be undone once it is true, so it is
        set only where it was asked for."""
        wanted = _payload(event_body(_draft(online_meeting=True), transaction_id="synthetic"))
        plain = _payload(event_body(_draft(), transaction_id="synthetic"))

        assert wanted["isOnlineMeeting"] is True
        assert wanted["onlineMeetingProvider"] == "teamsForBusiness"
        assert "isOnlineMeeting" not in plain
        assert "onlineMeetingProvider" not in plain

    def test_an_all_day_event_says_so(self) -> None:
        body = _payload(event_body(_draft(all_day=True), transaction_id="synthetic"))

        assert body["isAllDay"] is True


class TestTheTransactionId:
    def test_the_same_draft_to_the_same_calendar_composes_the_same_id(self) -> None:
        """Microsoft documents `transactionId` as the way a client keeps a retry from creating a
        second event, and a fresh id on every attempt is no protection at all."""
        one = _draft(attendees=(_SOMEBODY_ELSE,))
        again = _draft(attendees=(_SOMEBODY_ELSE,))

        assert transaction_id_for("me", one) == transaction_id_for("me", again)

    def test_reordering_the_addresses_composes_the_same_id(self) -> None:
        """The same invitation arrived twice, in whatever order a model listed the people in."""
        one = _draft(attendees=(_SOMEBODY_ELSE, "sam@example.invalid"))
        other = _draft(attendees=("sam@example.invalid", _SOMEBODY_ELSE))

        assert transaction_id_for("me", one) == transaction_id_for("me", other)

    @pytest.mark.parametrize(
        "other",
        [
            _draft(subject="Pricing review (moved)"),
            _draft(starts_at="2026-03-02T15:00"),
            _draft(ends_at="2026-03-02T16:00"),
            _draft(time_zone="Europe/Zurich"),
            _draft(all_day=True),
            _draft(attendees=(_SOMEBODY_ELSE,)),
            _draft(optional_attendees=(_SOMEBODY_ELSE,)),
        ],
        ids=["subject", "start", "end", "zone", "all-day", "attendee", "optional-attendee"],
    )
    def test_a_different_request_composes_a_different_id(self, other: EventDraft) -> None:
        assert transaction_id_for("me", _draft()) != transaction_id_for("me", other)

    def test_the_same_draft_on_another_calendar_composes_another_id(self) -> None:
        """Two calendars are two events, and one id would make the second create look redundant."""
        assert transaction_id_for("me", _draft()) != transaction_id_for(_CALENDAR_ID, _draft())

    def test_it_is_a_uuid_string_because_that_is_what_goes_on_the_wire(self) -> None:
        composed = transaction_id_for("me", _draft())

        assert str(uuid.UUID(composed)) == composed


class TestTheTwoPredicatesGraphCannotAnswer:
    """Graph documents no `$filter` over attendees, so both of these run over the rows a page
    already carries."""

    @pytest.mark.parametrize(
        "fragment", ["alex", "ALEX", "wilber", "alex@example.invalid", "example.invalid"]
    )
    def test_a_person_is_matched_by_name_or_by_address_in_either_case(self, fragment: str) -> None:
        event = Event(
            id=_EVENT_ID,
            organizer=Recipient(
                email_address=EmailAddress(name="Alex Wilber", address=_SOMEBODY_ELSE)
            ),
        )

        assert person_matches(event, fragment)

    def test_an_attendee_counts_as_much_as_the_organizer(self) -> None:
        event = Event(
            id=_EVENT_ID,
            organizer=Recipient(email_address=EmailAddress(name="Ada Lovelace", address=_MINE)),
            attendees=[
                Attendee(email_address=EmailAddress(name="Alex Wilber", address=_SOMEBODY_ELSE))
            ],
        )

        assert person_matches(event, "wilber")

    def test_nobody_by_that_name_does_not_match(self) -> None:
        event = Event(
            id=_EVENT_ID,
            organizer=Recipient(email_address=EmailAddress(name="Ada Lovelace", address=_MINE)),
        )

        assert not person_matches(event, "wilber")

    def test_an_event_with_no_people_on_it_matches_nobody(self) -> None:
        assert not person_matches(Event(id=_EVENT_ID), "wilber")

    @pytest.mark.parametrize("fragment", ["pricing", "PRICING", "review"])
    def test_a_subject_is_matched_in_either_case(self, fragment: str) -> None:
        assert subject_matches(Event(id=_EVENT_ID, subject="Pricing review"), fragment)

    def test_another_subject_does_not_match(self) -> None:
        assert not subject_matches(Event(id=_EVENT_ID, subject="Pricing review"), "invoice")

    def test_an_event_sent_without_a_subject_matches_nothing(self) -> None:
        assert not subject_matches(Event(id=_EVENT_ID), "pricing")


class TestReadingOneCalendar:
    async def test_no_named_calendar_reads_the_mailboxs_own(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get("/me/calendar").mock(
            return_value=httpx.Response(200, json=_calendar_payload())
        )

        found = await calendar_of(client, calendar_id=None)

        assert route.call_count == 1
        assert found.id == _CALENDAR_ID

    async def test_a_named_calendar_is_read_by_its_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The id route only: an id from another mailbox is one Graph answers an error to, so every
        handle this connector mints lives in the signed-in user's own mailbox."""
        route = graph.get(f"/me/calendars/{_CALENDAR_ID}").mock(
            return_value=httpx.Response(200, json=_calendar_payload(owner=_SOMEBODY_ELSE))
        )

        found = await calendar_of(client, calendar_id=_CALENDAR_ID)

        assert route.call_count == 1
        assert found.owner is not None and found.owner.address == _SOMEBODY_ELSE

    @pytest.mark.parametrize("calendar_id", [None, _CALENDAR_ID], ids=["default", "named"])
    async def test_both_routes_ask_for_the_one_shared_field_list(
        self, client: GraphServiceClient, graph: respx.MockRouter, calendar_id: str | None
    ) -> None:
        """Two routes, one projection. A field selected on one route and not the other is a row
        that reports `can_edit` from one tool and null from another."""
        path = "/me/calendar" if calendar_id is None else f"/me/calendars/{_CALENDAR_ID}"
        route = graph.get(path).mock(return_value=httpx.Response(200, json=_calendar_payload()))

        _ = await calendar_of(client, calendar_id=calendar_id)

        params = route.calls.last.request.url.params
        assert params["$select"].split(",") == list(CALENDAR_FIELDS)

    @pytest.mark.parametrize("calendar_id", [None, _CALENDAR_ID], ids=["default", "named"])
    async def test_neither_route_asks_graph_to_render_times_in_a_zone(
        self, client: GraphServiceClient, graph: respx.MockRouter, calendar_id: str | None
    ) -> None:
        """`Prefer: outlook.timezone` would make Graph render every time of every later request in
        one zone, and this connector converts with `zoneinfo` instead."""
        path = "/me/calendar" if calendar_id is None else f"/me/calendars/{_CALENDAR_ID}"
        route = graph.get(path).mock(return_value=httpx.Response(200, json=_calendar_payload()))

        _ = await calendar_of(client, calendar_id=calendar_id)

        assert "prefer" not in route.calls.last.request.headers
