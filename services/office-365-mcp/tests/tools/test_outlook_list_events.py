"""Microsoft interprets `startDateTime` and `endDateTime` by the offset written into the value
itself and by nothing else, so a bound rendered without an offset, or in the wrong zone, answers
a different week correctly.
"""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import cast

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
    is_cancelled: bool | None = False,
    sensitivity: str | None = "normal",
    event_type: str | None = "occurrence",
    series_master_id: str | None = "AAMkAGI2SYNTHETIC-series-0001=",
    owner_response: str | None = "organizer",
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
        **({} if is_cancelled is None else {"isCancelled": is_cancelled}),
        "type": event_type,
        "seriesMasterId": series_master_id,
        "sensitivity": sensitivity,
        "showAs": "busy",
        "location": {"displayName": "Room 3"},
        "isOnlineMeeting": True,
        "onlineMeeting": {"joinUrl": "https://teams.microsoft.invalid/l/meetup-join/synthetic"},
        "organizer": {"emailAddress": dict(organizer if organizer is not None else _ADA)},
        "isOrganizer": True,
        **(
            {}
            if owner_response is None
            else {"responseStatus": {"response": owner_response, "time": "0001-01-01T00:00:00Z"}}
        ),
        "attendees": [],
        "webLink": "https://outlook.office365.invalid/owa/?itemid=synthetic",
    }


def _page(*events: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(events)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _fields(node: object, at: str, *, root: Mapping[str, object]) -> dict[str, object]:
    """Pydantic publishes a nested model as a `$ref` into the schema's own `$defs` rather than
    inline, so a walk that skips it checks only the top level and calls that the whole answer."""
    schema = _resolved(node, root=root)
    found: dict[str, object] = {}
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, field in cast("Mapping[str, object]", properties).items():
            found[f"{at}.{name}"] = field
            found |= _fields(field, f"{at}.{name}", root=root)
    items = schema.get("items")
    if items is not None:
        found |= _fields(items, f"{at}[]", root=root)
    branches = schema.get("anyOf")
    if isinstance(branches, list):
        for branch in cast("Sequence[object]", branches):
            found |= _fields(branch, at, root=root)
    return found


def _resolved(node: object, *, root: Mapping[str, object]) -> Mapping[str, object]:
    schema = cast("Mapping[str, object]", node)
    reference = schema.get("$ref")
    if not isinstance(reference, str):
        return schema
    definitions = cast("Mapping[str, object]", root.get("$defs", {}))
    return cast("Mapping[str, object]", definitions[reference.removeprefix("#/$defs/")])


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
    async def test_a_call_that_narrows_nothing_sends_no_filter_at_all(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """The plain window is what almost every call asks for, and an empty `$filter=` is not the
        same request as no `$filter`."""
        _ = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        params = my_view.calls.last.request.url.params
        assert "$filter" not in params, "no narrowing argument was given, so none was composed"
        assert "$search" not in params, "a calendar view narrows by `$filter`, never by KQL"

    @pytest.mark.usefixtures("my_calendar")
    @pytest.mark.parametrize(
        ("cancelled", "expected"),
        [(False, "isCancelled eq false"), (True, "isCancelled eq true")],
    )
    async def test_cancelled_is_narrowed_by_microsoft_rather_than_over_the_rows(
        self, client: GraphServiceClient, my_view: respx.Route, cancelled: bool, expected: str
    ) -> None:
        """Against a live tenant `eq false` answered a whole 23-row window and `eq true` answered
        none of it, which partitions the window and so proves Graph evaluated the term."""
        _ = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            cancelled=cancelled,
            limit=25,
        )

        assert my_view.calls.last.request.url.params["$filter"] == expected, (
            "a narrowing this tool applies in process spends `limit` on rows it then discards"
        )

    @pytest.mark.usefixtures("my_calendar")
    @pytest.mark.parametrize(
        "owner_response", ["accepted", "tentativelyAccepted", "declined", "notResponded"]
    )
    async def test_an_owner_response_never_reaches_the_wire_at_all(
        self,
        client: GraphServiceClient,
        my_view: respx.Route,
        owner_response: lister.OwnerResponse,
    ) -> None:
        """`responseStatus/response` IS filterable on `calendarView` on its own, which is the trap:
        a live probe on 2026-09-10 found a nested path returns 500 as soon as it is conjoined with
        any other property, in both orders and parenthesised. So the one argument that could be
        pushed down alone is the one that must never be, because `cancelled=false` beside
        `owner_response="accepted"` is the combination a caller most wants and would crash."""
        _ = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            owner_response=owner_response,
            limit=25,
        )

        assert "$filter" not in my_view.calls.last.request.url.params, (
            "the owner's answer is compared over the rows; a conjoined nested path is a 500"
        )

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_subject_fragment_is_narrowed_by_microsoft_rather_than_over_the_rows(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        _ = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            subject_contains="pricing",
            limit=25,
        )

        assert my_view.calls.last.request.url.params["$filter"] == "contains(subject,'pricing')"

    @pytest.mark.usefixtures("my_calendar")
    async def test_an_apostrophe_in_a_subject_fragment_cannot_end_the_odata_literal(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """A quote left as it came closes the literal early and leaves the rest of the caller's own
        text standing as predicate syntax, which Graph answers instead of the question asked."""
        _ = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            subject_contains="o'brien retro",
            limit=25,
        )

        assert my_view.calls.last.request.url.params["$filter"] == (
            "contains(subject,'o''brien retro')"
        )

    @pytest.mark.usefixtures("my_calendar")
    async def test_the_owner_response_it_cannot_send_it_applies_to_the_rows_instead(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """The argument contributes nothing to the wire, so this is the only thing that makes it
        mean anything. Without this the tool would accept `owner_response` and silently ignore it.
        """
        _ = my_view.mock(
            return_value=_page(
                _event_payload("AAMkAGI2accepted==", owner_response="accepted"),
                _event_payload("AAMkAGI2declined==", owner_response="declined"),
                _event_payload("AAMkAGI2nothing==", owner_response=None),
            )
        )

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            owner_response="accepted",
            limit=25,
        )

        assert [row.owner_response for row in answer.events] == ["accepted"], (
            "the other answer and the row Graph recorded no answer on are both discarded here"
        )

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_row_graph_recorded_no_answer_on_is_not_a_notresponded(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """`notResponded` is an answer Microsoft states. A missing `responseStatus` is the absence
        of one, and reading it as `notResponded` would invent an invitation nobody was sent."""
        _ = my_view.mock(
            return_value=_page(_event_payload("AAMkAGI2nothing==", owner_response=None))
        )

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            owner_response="notResponded",
            limit=25,
        )

        assert answer.events == []

    @pytest.mark.usefixtures("my_calendar")
    @pytest.mark.parametrize(
        ("cancelled", "owner_response", "subject_contains", "expected"),
        [
            (False, "accepted", None, "isCancelled eq false"),
            (True, None, "pricing", "isCancelled eq true and contains(subject,'pricing')"),
            (None, "declined", "pricing", "contains(subject,'pricing')"),
            (
                False,
                "accepted",
                "pricing",
                "isCancelled eq false and contains(subject,'pricing')",
            ),
        ],
    )
    async def test_the_narrowing_arguments_that_were_given_are_anded_into_one_filter(
        self,
        client: GraphServiceClient,
        my_view: respx.Route,
        cancelled: bool | None,
        owner_response: lister.OwnerResponse | None,
        subject_contains: str | None,
        expected: str,
    ) -> None:
        """A live tenant honoured the two flat conjuncts joined this way, and a term this tool
        composed but Graph ignored would widen the answer without widening what the tool reports.
        `owner_response` is passed in every case here and contributes to none of them: it is the
        nested path that 500s the moment it is conjoined."""
        _ = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            cancelled=cancelled,
            owner_response=owner_response,
            subject_contains=subject_contains,
            limit=25,
        )

        assert my_view.calls.last.request.url.params["$filter"] == expected

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_filter_does_not_displace_the_order_the_rows_are_promised_in(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """`$filter` beside `$orderby=start/dateTime` returned the full row set against a live
        tenant, so neither parameter has to give way to the other."""
        _ = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            subject_contains="pricing",
            limit=7,
        )

        params = my_view.calls.last.request.url.params
        assert params["$orderby"] == "start/dateTime"
        assert params["$select"].split(",") == list(SUMMARY_FIELDS)
        assert params["$top"] == "7"

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
        rejects fails the whole request instead of costing one field."""
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
        assert row.owner_is_organizer is True, "Graph's `isOrganizer` is about the calendar's owner"
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
    async def test_omitting_cancelled_lists_the_called_off_rows_as_well(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """A cancelled event stays in the calendar until somebody removes it, so hiding it by
        default would answer "nothing is on" for a day that had a meeting until this morning."""
        my_view.mock(
            return_value=_page(
                _event_payload(_FIRST_ID, is_cancelled=True),
                _event_payload(_SECOND_ID, is_cancelled=False),
            )
        )

        answer = await lister.list_events(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert [event.cancelled for event in answer.events] == [True, False]
        assert "$filter" not in my_view.calls.last.request.url.params, (
            "an `isCancelled` term nobody asked for would hide a meeting called off this morning"
        )

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
    async def test_a_narrowed_window_microsoft_answered_with_nothing_is_not_capped(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """This is the difference between "nobody has such a meeting" and "this call did not reach
        it", and a model widens the window only for the second."""
        my_view.mock(return_value=_page())

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            subject_contains="pricing",
            limit=25,
        )

        assert answer.events == []
        assert answer.capped is False, "Microsoft finished the narrowed window, so nothing matched"

    @pytest.mark.usefixtures("my_calendar")
    async def test_a_narrowed_call_that_filled_the_limit_still_says_capped(
        self, client: GraphServiceClient, my_view: respx.Route
    ) -> None:
        """Narrowing runs inside the query, so every row that arrives already matched: `limit` is
        the only thing left that can stop the walk short."""
        my_view.mock(
            return_value=_page(
                _event_payload(_FIRST_ID),
                _event_payload(_SECOND_ID),
                _event_payload(_THIRD_ID),
            )
        )

        answer = await lister.list_events(
            client,
            starts_on=_MARCH_MONDAY,
            ends_on=_MARCH_SUNDAY,
            subject_contains="pricing",
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

    async def test_the_zone_refusal_warns_that_an_etc_gmt_key_reverses_its_sign(
        self, client: GraphServiceClient
    ) -> None:
        """`Etc/GMT+2` is a key the database holds, at two hours behind UTC. The refusal turns
        down `+02:00`, so it names that key as well and says which way the sign runs."""
        with pytest.raises(ToolError, match="Etc/GMT") as refused:
            _ = await lister.list_events(
                client,
                starts_on=_MARCH_MONDAY,
                ends_on=_MARCH_SUNDAY,
                time_zone="+02:00",
                limit=25,
            )

        assert "BEHIND UTC" in str(refused.value)

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
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters.get("required", []) == ["starts_on", "ends_on"]

    async def test_the_zone_defaults_to_utc_rather_than_to_a_guess(
        self, transport: httpx.AsyncClient
    ) -> None:
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
        """An optional string publishes as an `anyOf` of the constrained string and null, so the
        bound sits on the first branch rather than on the property."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert (
            tool.parameters["properties"]["subject_contains"]["anyOf"][0]["minLength"]
            == lister.MIN_FRAGMENT_CHARACTERS
        )

    async def test_no_argument_is_published_that_microsoft_cannot_narrow_on(
        self, transport: httpx.AsyncClient
    ) -> None:
        """Every spelling of `attendees/any(...)` is a 400 on a calendar view, and an
        `organizer/emailAddress/address` term answers 200 with no rows for an organizer that
        demonstrably has them — so this tool offers no way to ask for one person's meetings."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert "with_person" not in tool.parameters["properties"], (
            "an argument with no server-side route silently under-returns, which is unrecoverable"
        )

    async def test_the_description_sends_a_model_to_local_for_an_all_day_row(
        self, transport: httpx.AsyncClient
    ) -> None:
        """Graph holds an all-day event at midnight UTC, so `iso` names the day before only west
        of UTC; the description says so rather than claim `iso` carries no date at all."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        described = tool.description or ""
        assert "rather than `local`, the wall-clock text" in described
        assert "in a zone west of UTC it names the day before" in described
        assert "Take the date of an all-day row from `local`" in described

    async def test_the_zone_argument_says_which_way_an_etc_gmt_key_runs(
        self, transport: httpx.AsyncClient
    ) -> None:
        """`Etc/GMT+2` resolves, at two hours behind UTC, so this argument accepts it and answers
        the right meetings at the wrong hours. Nothing fails, so the argument says so."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        time_zone = cast("Mapping[str, object]", properties["time_zone"])
        described = str(time_zone["description"])
        assert "`Etc/GMT+2`" in described
        assert "BEHIND UTC" in described
        assert "`Europe/Berlin`" in described

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, object]", tool.output_schema)
        published = _fields(answer, lister.TOOL_NAME, root=answer)
        # Guards the guard: a walk that stopped descending passes by finding nothing to check.
        assert f"{lister.TOOL_NAME}.window.starts_at" in published
        assert f"{lister.TOOL_NAME}.events[].start.iso" in published
        assert f"{lister.TOOL_NAME}.calendar.owner.address" in published
        undescribed = sorted(
            path
            for path, field in published.items()
            if not cast("Mapping[str, object]", field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"


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
        assert "outlook_list_calendars" in lister.GRAPH_NOT_FOUND
