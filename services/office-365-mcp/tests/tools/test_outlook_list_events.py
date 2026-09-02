"""`outlook_list_events`: the window it asks for, the calendar it addresses, what it refuses.

The two window bounds are most of this file. Microsoft interprets `startDateTime` and `endDateTime`
by the offset written into the value itself and by nothing else, so a bound rendered without an
offset, or in the wrong zone, answers a different week correctly. The assertions below pin both
bounds byte for byte in a zone two hours ahead of UTC and in UTC, pin that no
`Prefer: outlook.timezone` reaches Graph, and pin that the conversion happens here instead.

Every response body here is synthesised. None came from a real mailbox.
"""

from datetime import date, timedelta

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.calendar import MAX_WINDOW_DAYS, SUMMARY_FIELDS
from office_365_mcp.shared.handles import CalendarHandle, EventHandle, MailMessageHandle
from office_365_mcp.tools import outlook_list_events as lister

from .conftest import GRAPH_V1

# No `=` in a calendar id: this half of the pair travels in the URL path, and an assertion on a
# path respx never matched proves nothing about the route the tool addressed.
_MY_CALENDAR_ID = "AAMkADAwSYNTHETIC-calendar-default"
_SHARED_CALENDAR_ID = "AAMkADAwSYNTHETIC-calendar-shared"

_MY_CALENDAR = "/me/calendar"
_MY_VIEW = f"/me/calendars/{_MY_CALENDAR_ID}/calendarView"
_SHARED_CALENDAR = f"/me/calendars/{_SHARED_CALENDAR_ID}"
_SHARED_VIEW = f"/me/calendars/{_SHARED_CALENDAR_ID}/calendarView"

_FIRST_ID = "AAMkAGI2SYNTHETIC-immutable-0001="
_SECOND_ID = "AAMkAGI2SYNTHETIC-immutable-0002="
_THIRD_ID = "AAMkAGI2SYNTHETIC-immutable-0003="

# July in Zurich is UTC+2, so the offset in a rendered bound is visible rather than assumed.
_SUMMER_MONDAY = date(2026, 7, 6)
_SUMMER_SUNDAY = date(2026, 7, 12)
_ZURICH = "Europe/Zurich"

_MARCH_MONDAY = date(2026, 3, 2)
_MARCH_SUNDAY = date(2026, 3, 8)

_ADA = {"name": "Ada Lovelace", "address": "ada@example.invalid"}
_DANA = {"name": "Dana Swope", "address": "dana@example.invalid"}
_BOB = {"name": "Bob Vance", "address": "bob@vance.invalid"}


def _calendar_payload(
    calendar_id: str,
    *,
    name: str | None = "Calendar",
    owner: dict[str, str] | None = None,
    can_edit: bool | None = True,
    can_view_private_items: bool | None = True,
    is_default: bool | None = True,
) -> dict[str, object]:
    return {
        "id": calendar_id,
        "name": name,
        "owner": dict(owner if owner is not None else _ADA),
        "canEdit": can_edit,
        "canShare": True,
        "canViewPrivateItems": can_view_private_items,
        "isDefaultCalendar": is_default,
        "isTallyingResponses": True,
        "allowedOnlineMeetingProviders": ["teamsForBusiness"],
        "defaultOnlineMeetingProvider": "teamsForBusiness",
    }


def _event_payload(
    event_id: str,
    *,
    subject: str | None = "Pricing review",
    start: str = "2026-07-06T13:00:00.0000000",
    end: str = "2026-07-06T14:00:00.0000000",
    time_zone: str | None = "UTC",
    organizer: dict[str, str] | None = None,
    attendees: tuple[dict[str, str], ...] = (),
    is_cancelled: bool | None = False,
    sensitivity: str | None = "normal",
    event_type: str | None = "occurrence",
    series_master_id: str | None = "AAMkAGI2SYNTHETIC-series-0001=",
) -> dict[str, object]:
    """`timeZone` is `UTC` because this tool sends no `Prefer: outlook.timezone`, and Microsoft
    documents UTC as what a calendar view answers in without it."""
    return {
        "id": event_id,
        "subject": subject,
        "bodyPreview": "Agenda attached.",
        "start": {"dateTime": start, "timeZone": time_zone},
        "end": {"dateTime": end, "timeZone": time_zone},
        "isAllDay": False,
        "isCancelled": is_cancelled,
        "type": event_type,
        "seriesMasterId": series_master_id,
        "sensitivity": sensitivity,
        "showAs": "busy",
        "location": {"displayName": "Room 3"},
        "isOnlineMeeting": True,
        "onlineMeeting": {"joinUrl": "https://teams.microsoft.invalid/l/meetup-join/synthetic"},
        "organizer": {"emailAddress": dict(organizer if organizer is not None else _ADA)},
        "isOrganizer": True,
        "responseStatus": {"response": "organizer", "time": "0001-01-01T00:00:00Z"},
        "attendees": [
            {
                "type": "required",
                "status": {"response": "none", "time": "0001-01-01T00:00:00Z"},
                "emailAddress": dict(attendee),
            }
            for attendee in attendees
        ],
        "webLink": "https://outlook.office365.invalid/owa/?itemid=synthetic",
    }


def _page(*events: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(events)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


@pytest.fixture
def my_calendar(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_MY_CALENDAR).mock(
        return_value=httpx.Response(200, json=_calendar_payload(_MY_CALENDAR_ID))
    )


@pytest.fixture
def my_view(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_MY_VIEW).mock(return_value=_page(_event_payload(_FIRST_ID)))


class TestTheQueryItComposes:
    @pytest.mark.usefixtures("my_calendar")
    async def test_both_bounds_carry_the_offset_of_the_zone_that_was_asked_for(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """Microsoft interprets these two by the offset written into the value and by nothing
        else, so a bound with no offset is read as UTC and asks about a different week."""
        _ = await lister.list_events(
            client,
            starts_on=_SUMMER_MONDAY,
            ends_on=_SUMMER_SUNDAY,
            time_zone=_ZURICH,
            limit=25,
        )

        params = my_view.calls.last.request.url.params
        assert params["startDateTime"] == "2026-07-06T00:00:00+02:00"
        assert params["endDateTime"] == "2026-07-13T00:00:00+02:00"

    @pytest.mark.usefixtures("my_calendar")
    async def test_the_end_bound_opens_the_day_after_the_last_one_asked_for(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """A window whose two dates are the same day holds that whole day, which needs an end bound
        24 hours later rather than an equal one."""
        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_MONDAY, limit=25
        )

        params = my_view.calls.last.request.url.params
        assert params["startDateTime"] == "2026-03-02T00:00:00+00:00"
        assert params["endDateTime"] == "2026-03-03T00:00:00+00:00"

    @pytest.mark.usefixtures("my_calendar")
    async def test_the_default_zone_renders_utc_bounds_rather_than_naked_ones(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        params = my_view.calls.last.request.url.params
        assert params["startDateTime"] == "2026-03-02T00:00:00+00:00"
        assert params["endDateTime"] == "2026-03-09T00:00:00+00:00"

    @pytest.mark.usefixtures("my_calendar")
    async def test_it_asks_for_the_shared_summary_fields_and_nothing_else(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """Microsoft warns that a large page with no `$select` risks a gateway timeout, and
        `createdDateTime` and `lastModifiedDateTime` do not support `$select` at all."""
        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        params = my_view.calls.last.request.url.params
        assert params["$select"].split(",") == list(SUMMARY_FIELDS)

    @pytest.mark.usefixtures("my_calendar")
    async def test_the_callers_limit_is_the_page_size_it_asks_microsoft_for(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """Microsoft documents a calendar view's `$top` as a minimum of 1 and a maximum of 1000,
        and this tool's own cap is far inside that."""
        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=7
        )

        assert my_view.calls.last.request.url.params["$top"] == "7"

    @pytest.mark.usefixtures("my_calendar")
    async def test_start_order_is_asked_for_and_is_the_order_this_tool_promises(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert my_view.calls.last.request.url.params["$orderby"] == "start/dateTime"

    @pytest.mark.usefixtures("my_calendar")
    @pytest.mark.parametrize(
        ("with_person", "subject_contains"),
        [(None, None), ("dana", None), (None, "pricing"), ("dana", "pricing")],
    )
    async def test_no_argument_ever_reaches_the_query_as_a_filter(
        self,
        client: GraphServiceClient,
        my_view: respx.Route,
        with_person: str | None,
        subject_contains: str | None,
    ) -> None:
        """Microsoft documents no `$filter` over `attendees`, and a filter composed against
        undocumented support answers `200 OK` and the wrong rows."""
        _ = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            with_person=with_person,
            subject_contains=subject_contains,
            limit=25,
        )

        params = my_view.calls.last.request.url.params
        assert "$filter" not in params, "both fragments are predicates over the rows"
        assert "$search" not in params

    @pytest.mark.usefixtures("my_calendar")
    async def test_the_listing_asks_for_ids_that_outlive_the_event_being_filed(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """The same preference outlook_read_event sends on the way in: without it these handles
        would be `RestId`s, which die the moment Outlook moves the event."""
        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert 'IdType="ImmutableId"' in my_view.calls.last.request.headers["Prefer"]

    @pytest.mark.usefixtures("my_calendar")
    async def test_the_preference_is_supplied_again_for_every_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`PageIterator` starts from an empty header collection, so a page fetched without it
        would answer in the other id space and mint handles that 404."""
        cursor = graph.get(_MY_VIEW, params={"$skiptoken": "second"}).mock(
            return_value=_page(_event_payload(_SECOND_ID))
        )
        graph.get(_MY_VIEW).mock(
            return_value=_page(
                _event_payload(_FIRST_ID),
                next_link=f"{GRAPH_V1}{_MY_VIEW}?$skiptoken=second",
            )
        )

        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert 'IdType="ImmutableId"' in cursor.calls.last.request.headers["Prefer"]

    @pytest.mark.usefixtures("my_calendar", "my_view")
    async def test_no_request_asks_exchange_to_render_the_times(
        self, client: GraphServiceClient, my_calendar: respx.Route, my_view: respx.Route
    ) -> None:
        """`Prefer: outlook.timezone` would move the conversion into Exchange, where a zone name it
        rejects fails the whole request instead of costing one field. This tool converts with
        `zoneinfo` and leaves Microsoft answering in UTC."""
        _ = await lister.list_events(
            client,
            starts_on=_SUMMER_MONDAY,
            ends_on=_SUMMER_SUNDAY,
            time_zone=_ZURICH,
            limit=25,
        )

        assert "outlook.timezone" not in my_view.calls.last.request.headers["Prefer"]
        assert "Prefer" not in my_calendar.calls.last.request.headers

    @pytest.mark.usefixtures("my_view")
    async def test_the_preference_does_not_leak_onto_the_calendar_read(
        self, client: GraphServiceClient, my_calendar: respx.Route
    ) -> None:
        """Kiota's `RequestConfiguration.headers` default is one collection shared process-wide, so
        a preference added to it would reach the calendar read of every later call."""
        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )
        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert my_calendar.call_count == 2
        assert "Prefer" not in my_calendar.calls.last.request.headers


class TestTheCalendarItAddresses:
    @pytest.mark.usefixtures("my_calendar", "my_view")
    async def test_no_calendar_ref_reads_the_mailboxs_own_primary_calendar(
        self, client: GraphServiceClient, graph: respx.MockRouter, my_view: respx.Route
    ) -> None:
        """`GET /me/calendar` is the primary calendar, and `GET /me/calendars/{id}` needs an id
        nobody supplied."""
        shared = graph.get(_SHARED_CALENDAR)

        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert my_view.call_count == 1
        assert shared.call_count == 0, "no handle named a calendar, so none was addressed by id"

    @pytest.mark.usefixtures("my_calendar", "my_view")
    async def test_a_calendar_handle_reads_the_calendar_it_addresses(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        my_calendar: respx.Route,
        my_view: respx.Route,
    ) -> None:
        shared = graph.get(_SHARED_CALENDAR).mock(
            return_value=httpx.Response(
                200,
                json=_calendar_payload(
                    _SHARED_CALENDAR_ID, name="Dana Swope", owner=_DANA, is_default=False
                ),
            )
        )
        shared_view = graph.get(_SHARED_VIEW).mock(return_value=_page(_event_payload(_FIRST_ID)))

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            calendar_ref=CalendarHandle(_SHARED_CALENDAR_ID).uri,
            limit=25,
        )

        assert shared.call_count == 1
        assert shared_view.call_count == 1
        assert my_calendar.call_count == 0, "a handle addresses one calendar, not the default one"
        assert my_view.call_count == 0
        assert answer.calendar.name == "Dana Swope"

    @pytest.mark.usefixtures("my_calendar", "my_view")
    async def test_the_view_is_addressed_by_the_id_the_calendar_read_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph puts no calendar id on a calendar view row, so the id the pre-read reported is the
        only one that can address the view or complete a handle."""
        elsewhere = graph.get("/me/calendar/calendarView")

        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert elsewhere.call_count == 0, "the primary calendar is addressed by its id here too"


class TestWhatItAnswers:
    @pytest.mark.usefixtures("my_calendar")
    async def test_each_row_carries_the_handle_that_reads_the_event(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """Both halves: the calendar id from the pre-read, and the event id from the row."""
        my_view.mock(return_value=_page(_event_payload(_FIRST_ID), _event_payload(_SECOND_ID)))

        answer = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert [event.uri for event in answer.events] == [
            EventHandle(_MY_CALENDAR_ID, _FIRST_ID).uri,
            EventHandle(_MY_CALENDAR_ID, _SECOND_ID).uri,
        ]

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_shared_calendars_rows_carry_that_calendars_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_SHARED_CALENDAR).mock(
            return_value=httpx.Response(
                200, json=_calendar_payload(_SHARED_CALENDAR_ID, owner=_DANA, is_default=False)
            )
        )
        graph.get(_SHARED_VIEW).mock(return_value=_page(_event_payload(_FIRST_ID)))

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            calendar_ref=CalendarHandle(_SHARED_CALENDAR_ID).uri,
            limit=25,
        )

        assert [event.uri for event in answer.events] == [
            EventHandle(_SHARED_CALENDAR_ID, _FIRST_ID).uri
        ]

    @pytest.mark.usefixtures("my_calendar")
    async def test_the_rows_are_converted_into_the_zone_that_was_asked_for(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """Microsoft answers in UTC without `Prefer: outlook.timezone`, and Graph's own two values
        come back beside the converted one rather than instead of it."""
        my_view.mock(
            return_value=_page(
                _event_payload(
                    _FIRST_ID,
                    start="2026-07-06T13:00:00.0000000",
                    end="2026-07-06T14:00:00.0000000",
                    time_zone="UTC",
                )
            )
        )

        answer = await lister.list_events(
            client,
            starts_on=_SUMMER_MONDAY,
            ends_on=_SUMMER_SUNDAY,
            time_zone=_ZURICH,
            limit=25,
        )

        row = answer.events[0]
        assert row.start is not None
        assert row.start.iso == "2026-07-06T15:00:00+02:00"
        assert row.start.local == "2026-07-06T13:00:00.0000000"
        assert row.start.time_zone == "UTC"
        assert row.end is not None
        assert row.end.iso == "2026-07-06T16:00:00+02:00"

    @pytest.mark.usefixtures("my_calendar", "my_view")
    async def test_the_window_that_was_asked_for_comes_back_with_the_rows(
        self, client: GraphServiceClient
    ) -> None:
        """The zone decides which week the answer is about, so an answer that does not state it
        cannot be checked."""
        answer = await lister.list_events(
            client,
            starts_on=_SUMMER_MONDAY,
            ends_on=_SUMMER_SUNDAY,
            time_zone=_ZURICH,
            limit=25,
        )

        assert answer.window.starts_at == "2026-07-06T00:00:00+02:00"
        assert answer.window.ends_at == "2026-07-13T00:00:00+02:00"
        assert answer.window.time_zone == _ZURICH

    @pytest.mark.usefixtures("my_calendar", "my_view")
    async def test_the_calendar_envelope_says_whose_it_is_and_leaves_is_mine_unknown(
        self, client: GraphServiceClient
    ) -> None:
        """This tool reads no `/me`, so `is_mine` is null rather than a guess. Null means unknown
        and never false."""
        answer = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert answer.calendar.uri == CalendarHandle(_MY_CALENDAR_ID).uri
        assert answer.calendar.owner is not None
        assert answer.calendar.owner.address == "ada@example.invalid"
        assert answer.calendar.is_mine is None
        assert answer.calendar.can_view_private_items is True

    @pytest.mark.usefixtures("my_calendar", "my_view")
    async def test_it_reports_the_fields_a_model_triages_on(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        row = answer.events[0]
        assert row.subject == "Pricing review"
        assert row.preview == "Agenda attached."
        assert row.location == "Room 3"
        assert row.kind == "occurrence"
        assert row.in_series is True
        assert row.sensitivity == "normal"
        assert row.cancelled is False
        assert row.owner_response == "organizer"
        assert row.join_url == "https://teams.microsoft.invalid/l/meetup-join/synthetic"

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_canceled_row_is_flagged_rather_than_dropped(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """A canceled event stays in a calendar until somebody removes it, so hiding it here would
        report a slot as free while Outlook still shows it."""
        my_view.mock(return_value=_page(_event_payload(_FIRST_ID, is_cancelled=True)))

        answer = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert len(answer.events) == 1
        assert answer.events[0].cancelled is True

    @pytest.mark.usefixtures("my_calendar")
    async def test_the_order_graph_returned_is_the_order_answered(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        my_view.mock(
            return_value=_page(
                _event_payload(_FIRST_ID, start="2026-03-02T09:00:00.0000000"),
                _event_payload(_SECOND_ID, start="2026-03-04T11:00:00.0000000"),
            )
        )

        answer = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert [event.start.iso for event in answer.events if event.start is not None] == [
            "2026-03-02T09:00:00+00:00",
            "2026-03-04T11:00:00+00:00",
        ]

    @pytest.mark.usefixtures("my_calendar")
    async def test_with_person_keeps_the_row_that_person_organized(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        my_view.mock(
            return_value=_page(
                _event_payload(_FIRST_ID, organizer=_DANA, attendees=(_BOB,)),
                _event_payload(_SECOND_ID, organizer=_ADA, attendees=(_BOB,)),
            )
        )

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            with_person="dana@example.invalid",
            limit=25,
        )

        assert [event.uri for event in answer.events] == [
            EventHandle(_MY_CALENDAR_ID, _FIRST_ID).uri
        ]

    @pytest.mark.usefixtures("my_calendar")
    async def test_with_person_keeps_the_row_that_person_was_only_invited_to(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """A meeting with Dana is one Dana attends, whoever sent the invitation."""
        my_view.mock(
            return_value=_page(
                _event_payload(_FIRST_ID, organizer=_ADA, attendees=(_BOB,)),
                _event_payload(_SECOND_ID, organizer=_ADA, attendees=(_DANA,)),
            )
        )

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            with_person="dana@example.invalid",
            limit=25,
        )

        assert [event.uri for event in answer.events] == [
            EventHandle(_MY_CALENDAR_ID, _SECOND_ID).uri
        ]

    @pytest.mark.usefixtures("my_calendar")
    async def test_with_person_drops_a_row_naming_nobody_who_was_asked_for(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        my_view.mock(
            return_value=_page(_event_payload(_FIRST_ID, organizer=_ADA, attendees=(_BOB,)))
        )

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            with_person="dana@example.invalid",
            limit=25,
        )

        assert answer.events == []

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_person_fragment_matches_a_display_name_without_regard_to_case(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """A user names a colleague, so the fragment has to reach a display name and not only an
        address."""
        my_view.mock(return_value=_page(_event_payload(_FIRST_ID, attendees=(_DANA,))))

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            with_person="dana swope",
            limit=25,
        )

        assert len(answer.events) == 1

    @pytest.mark.usefixtures("my_calendar")
    async def test_subject_contains_keeps_the_rows_whose_subject_holds_it(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        my_view.mock(
            return_value=_page(
                _event_payload(_FIRST_ID, subject="Quarterly pricing review"),
                _event_payload(_SECOND_ID, subject="Team lunch"),
            )
        )

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            subject_contains="PRICING",
            limit=25,
        )

        assert [event.subject for event in answer.events] == ["Quarterly pricing review"]

    @pytest.mark.usefixtures("my_calendar")
    async def test_both_fragments_together_narrow_rather_than_widen(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """A caller who names a person and a subject asked about one meeting, so a row has to
        satisfy both rather than either."""
        my_view.mock(
            return_value=_page(
                _event_payload(_FIRST_ID, subject="Pricing review", attendees=(_DANA,)),
                _event_payload(_SECOND_ID, subject="Pricing review", attendees=(_BOB,)),
                _event_payload(_THIRD_ID, subject="Team lunch", attendees=(_DANA,)),
            )
        )

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            with_person="dana@example.invalid",
            subject_contains="pricing",
            limit=25,
        )

        assert [event.uri for event in answer.events] == [
            EventHandle(_MY_CALENDAR_ID, _FIRST_ID).uri
        ]

    @pytest.mark.usefixtures("my_calendar")
    async def test_the_pages_of_a_window_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The cursor route is registered before the bare one, which respx matches in registration
        order: the bare path matches a `$skiptoken` request too and would answer every page."""
        graph.get(_MY_VIEW, params={"$skiptoken": "second"}).mock(
            return_value=_page(_event_payload(_SECOND_ID))
        )
        graph.get(_MY_VIEW).mock(
            return_value=_page(
                _event_payload(_FIRST_ID),
                next_link=f"{GRAPH_V1}{_MY_VIEW}?$skiptoken=second",
            )
        )

        answer = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert [event.uri for event in answer.events] == [
            EventHandle(_MY_CALENDAR_ID, _FIRST_ID).uri,
            EventHandle(_MY_CALENDAR_ID, _SECOND_ID).uri,
        ]
        assert answer.capped is False, "the walk reached the end of the window"

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_cap_that_left_more_of_the_window_on_offer_says_capped(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        my_view.mock(return_value=_page(_event_payload(_FIRST_ID), _event_payload(_SECOND_ID)))

        answer = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=1
        )

        assert [event.uri for event in answer.events] == [
            EventHandle(_MY_CALENDAR_ID, _FIRST_ID).uri
        ]
        assert answer.capped is True

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_window_filled_exactly_by_its_own_end_is_not_capped(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """`capped` means a cap stopped the walk with more still on offer, never that the answer
        was short."""
        my_view.mock(return_value=_page(_event_payload(_FIRST_ID), _event_payload(_SECOND_ID)))

        answer = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=2
        )

        assert len(answer.events) == 2
        assert answer.capped is False

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_predicate_that_discarded_every_row_of_a_finished_window_is_not_capped(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """This is the difference between "nobody has such a meeting" and "this call did not reach
        it", and a model widens the window only for the second."""
        my_view.mock(
            return_value=_page(
                _event_payload(_FIRST_ID, attendees=(_BOB,)),
                _event_payload(_SECOND_ID, attendees=(_BOB,)),
            )
        )

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            with_person="dana@example.invalid",
            limit=25,
        )

        assert answer.events == []
        assert answer.capped is False, "the window ran out on its own, so nothing matched in it"

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_predicate_that_filled_the_limit_with_rows_still_on_offer_says_capped(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        my_view.mock(
            return_value=_page(
                _event_payload(_FIRST_ID, attendees=(_DANA,)),
                _event_payload(_SECOND_ID, attendees=(_DANA,)),
                _event_payload(_THIRD_ID, attendees=(_DANA,)),
            )
        )

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            with_person="dana@example.invalid",
            limit=2,
        )

        assert len(answer.events) == 2
        assert answer.capped is True

    @pytest.mark.usefixtures("my_calendar")
    async def test_an_empty_window_answers_no_rows_and_no_cap(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        my_view.mock(return_value=_page())

        answer = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert answer.events == []
        assert answer.capped is False, "an empty window is the whole of it, not a cap"


class TestWhatItRefuses:
    async def test_a_window_that_runs_backwards_never_reaches_graph(
        self, client: GraphServiceClient, my_calendar: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="backwards"):
            _ = await lister.list_events(
                client, starts_on=_MARCH_SUNDAY, ends_on=_MARCH_MONDAY, limit=25
            )

        assert my_calendar.call_count == 0

    async def test_a_window_wider_than_the_cap_never_reaches_graph(
        self, client: GraphServiceClient, my_calendar: respx.Route
    ) -> None:
        """A calendar view expands every recurring series into one row per occurrence, so a year of
        a daily stand-up is hundreds of rows of one meeting."""
        with pytest.raises(ToolError, match="wider than"):
            _ = await lister.list_events(
                client, starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31), limit=25
            )

        assert my_calendar.call_count == 0

    async def test_the_widest_window_the_cap_allows_is_accepted(
        self, client: GraphServiceClient, my_calendar: respx.Route, my_view: respx.Route
    ) -> None:
        """Both dates are inside the window, so the cap counts the days covered rather than the
        distance between the two dates."""
        opens = date(2026, 1, 1)

        _ = await lister.list_events(
            client,
            starts_on=opens,
            ends_on=opens + timedelta(days=MAX_WINDOW_DAYS - 1),
            limit=25,
        )

        assert my_calendar.call_count == 1
        assert my_view.call_count == 1

    @pytest.mark.parametrize(
        "time_zone",
        [
            "W. Europe Standard Time",
            "Pacific Standard Time",
            "Zurich",
            "Switzerland",
            "+02:00",
            "",
        ],
    )
    async def test_a_zone_zoneinfo_cannot_resolve_never_reaches_graph(
        self, client: GraphServiceClient, my_calendar: respx.Route, time_zone: str
    ) -> None:
        """Graph accepts a Windows zone name in an event's own `timeZone`, so a model that read one
        off a previous answer arrives here with it. This argument is IANA only."""
        with pytest.raises(ToolError, match="IANA"):
            _ = await lister.list_events(
                client,
                starts_on=_MARCH_MONDAY,
                ends_on=_MARCH_SUNDAY,
                time_zone=time_zone,
                limit=25,
            )

        assert my_calendar.call_count == 0

    async def test_the_zone_refusal_names_the_default_so_the_argument_can_be_dropped(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="`UTC` is the default"):
            _ = await lister.list_events(
                client,
                starts_on=_MARCH_MONDAY,
                ends_on=_MARCH_SUNDAY,
                time_zone="W. Europe Standard Time",
                limit=25,
            )

    @pytest.mark.parametrize(
        "calendar_ref",
        [
            "Calendar",
            "dana@example.invalid",
            _SHARED_CALENDAR_ID,
            "outlook:///calendars/",
            EventHandle(_MY_CALENDAR_ID, _FIRST_ID).uri,
            MailMessageHandle(_FIRST_ID).uri,
        ],
    )
    async def test_a_calendar_ref_that_is_not_a_calendar_handle_never_reaches_graph(
        self, client: GraphServiceClient, my_calendar: respx.Route, calendar_ref: str
    ) -> None:
        with pytest.raises(ToolError, match="calendar handle"):
            _ = await lister.list_events(
                client,
                starts_on=_MARCH_MONDAY,
                ends_on=_MARCH_SUNDAY,
                calendar_ref=calendar_ref,
                limit=25,
            )

        assert my_calendar.call_count == 0

    async def test_the_handle_refusal_names_the_tool_that_mints_one(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_calendars"):
            _ = await lister.list_events(
                client,
                starts_on=_MARCH_MONDAY,
                ends_on=_MARCH_SUNDAY,
                calendar_ref="Calendar",
                limit=25,
            )

    @pytest.mark.parametrize("limit", [0, lister.MAX_RESULTS + 1])
    async def test_a_limit_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await lister.list_events(
                client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=limit
            )


class TestTheSchemaItPublishes:
    async def test_the_window_is_the_only_thing_a_caller_has_to_supply(
        self, transport: httpx.AsyncClient
    ) -> None:
        """Every other argument narrows an answer this tool gives without it."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters.get("required", []) == ["starts_on", "ends_on"]

    async def test_the_zone_defaults_to_utc_rather_than_to_a_guess(
        self, transport: httpx.AsyncClient
    ) -> None:
        """A guess at the user's zone reads as a fact about their calendar, and an hour is exactly
        the size of mistake nobody notices."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters["properties"]["time_zone"]["default"] == "UTC"

    async def test_the_bounds_on_limit_are_published_rather_than_only_asserted(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters["properties"]["limit"]["minimum"] == 1, (
            "Microsoft refuses a calendar view with a `$top` below 1"
        )
        assert tool.parameters["properties"]["limit"]["maximum"] == lister.MAX_RESULTS
        assert tool.parameters["properties"]["limit"]["default"] == 25

    async def test_a_fragment_too_short_to_filter_anything_is_refused_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        """One character matches most of a calendar while reading as a filter that worked.

        An optional string publishes as an `anyOf` of the constrained string and null, so the
        bound sits on the first branch rather than on the property.
        """
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        for argument in ("with_person", "subject_contains"):
            assert (
                tool.parameters["properties"][argument]["anyOf"][0]["minLength"]
                == lister.MIN_FRAGMENT_CHARACTERS
            ), argument


class TestGraphFailures:
    async def test_a_refused_calendar_read_stops_before_the_events_are_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter, my_view: respx.Route
    ) -> None:
        graph.get(_MY_CALENDAR).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.list_events(
                client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
            )

        assert my_view.call_count == 0

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        my_view.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_events(
                client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
            )

    def test_the_permissions_are_the_ones_microsoft_documents(self) -> None:
        """`Calendars.Read` reads the user's own calendars, and `Calendars.Read.Shared` is what
        makes a delegated calendar legible at all."""
        assert lister.GRAPH_PERMISSIONS == ("Calendars.Read", "Calendars.Read.Shared")

    def test_a_calendar_that_will_not_resolve_is_answered_with_the_recovery_that_fits(self) -> None:
        """A 404 here is not the default "check you copied the id" advice: the way in is a handle
        this connector minted, so the recovery is to list the calendars again."""
        assert "outlook_list_calendars" in lister.GRAPH_NOT_FOUND
