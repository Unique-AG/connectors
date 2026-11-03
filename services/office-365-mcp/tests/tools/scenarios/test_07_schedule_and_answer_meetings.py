import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import cast
from urllib.parse import unquote

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import (
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    InputRequiredResult,
    InputResponse,
    TextContent,
)
from mcp.types import ElicitResult as CarriedAnswer

from tests.conftest import RecordedSleeps
from tests.e2e.test_scenarios import build_server, patch_obo
from tests.graph_fixtures import E2E, Json

from .support import Person, call, response, serve

type Row = Mapping[str, object]

_ZURICH = "Europe/Zurich"
_MIA: Row = {"name": "Mia Keller", "address": "mia@example.test"}
_ANNA: Row = {"name": "Anna Meier", "address": "anna@example.test"}
_TOM: Row = {"name": "Tom Weber", "address": "tom@example.test"}
_PRIYA: Row = {"name": "Priya Rao", "address": "priya@example.test"}
_CALENDAR_ID = "AAMkSYNTHETIC-calendar-default"
_LAUNCH = "launch-review"
_DESIGN = "design-review"
_BUDGET = "budget-review"
_SYNC = "team-sync-thursday"
_SERIES = "team-sync-series"
_MONDAY = {"starts_at": "2026-11-02T14:00", "ends_at": "2026-11-02T14:30"}
_RECORDED_CREATE = "rec-tool-outlook_create_event-simple"
_MUMBAI = "India Standard Time"

_TOO_MANY: Json = {
    "status": 429,
    "headers": {"Retry-After": "30"},
    "body": "error.TooManyRequests.json",
}

_REFUSALS = [
    pytest.param(
        {"status": 401, "body": "error.InvalidAuthenticationToken.json"},
        "Ask the user to sign in to this connector again",
        id="expired-sign-in",
    ),
    pytest.param(
        {"status": 403, "body": "error.accessDenied.json"},
        "Ask a Microsoft 365 administrator to grant the delegated permission",
        id="no-access",
    ),
    pytest.param(
        _TOO_MANY, "asked to be left alone for 30 seconds. Retry after that, not sooner", id="busy"
    ),
]

_REJECTION = {"error": {"code": "ErrorInvalidRequest", "message": "The start is in the past."}}


type Fault = Callable[[httpx.Request], httpx.Response] | type[Exception]

_call = cast("Callable[..., Awaitable[Row]]", call)


def _reply(spec: Json) -> Fault:
    def answer(_request: httpx.Request) -> httpx.Response:
        return response(spec)

    return answer


def _rejection() -> Fault:
    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=_REJECTION)

    return answer


def _path(event_id: str) -> str:
    return f"/me/calendars/{_CALENDAR_ID}/events/{event_id}"


def _uri(event_id: str) -> str:
    return f"outlook:///events/{_CALENDAR_ID}/{event_id}"


def _attendee(person: Row, answer: str = "none") -> dict[str, object]:
    return {
        "emailAddress": dict(person),
        "type": "required",
        "status": {"response": answer, "time": "0001-01-01T00:00:00Z"},
    }


def _event(
    event_id: str,
    subject: str,
    *,
    organizer: Row = _MIA,
    attendees: Sequence[Row] = (),
    kind: str = "singleInstance",
    series: str | None = None,
    start: str = "2026-11-06T09:00:00",
) -> dict[str, object]:
    mine = organizer == _MIA
    return {
        "id": event_id,
        "subject": subject,
        "bodyPreview": f"About {subject}.",
        "start": {"dateTime": f"{start}.0000000", "timeZone": "UTC"},
        "end": {"dateTime": f"{start[:11]}09:30:00.0000000", "timeZone": "UTC"},
        "isAllDay": False,
        "isCancelled": False,
        "type": kind,
        "seriesMasterId": series,
        "sensitivity": "normal",
        "showAs": "busy",
        "location": {"displayName": ""},
        "isOnlineMeeting": False,
        "organizer": {"emailAddress": dict(organizer)},
        "isOrganizer": mine,
        "responseStatus": {
            "response": "organizer" if mine else "notResponded",
            "time": "0001-01-01T00:00:00Z",
        },
        "attendees": [_attendee(one) for one in attendees],
        "allowNewTimeProposals": True,
        "categories": [],
        "importance": "normal",
        "webLink": "https://outlook.office365.com/owa/?itemid=synthetic",
    }


def _calendar() -> dict[str, object]:
    return {
        "id": _CALENDAR_ID,
        "name": "Calendar",
        "owner": dict(_MIA),
        "canEdit": True,
        "canShare": True,
        "canViewPrivateItems": True,
        "isDefaultCalendar": True,
        "isTallyingResponses": True,
        "allowedOnlineMeetingProviders": ["teamsForBusiness"],
        "defaultOnlineMeetingProvider": "teamsForBusiness",
    }


def _stored(graph: respx.MockRouter, *events: dict[str, object]) -> None:
    _ = graph.get("/me/calendar").mock(return_value=httpx.Response(200, json=_calendar()))
    for stored in events:
        _ = graph.get(_path(str(stored["id"]))).mock(return_value=httpx.Response(200, json=stored))


def _posted(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _recorded(body: str) -> dict[str, object]:
    return cast("dict[str, object]", json.loads((E2E / "bodies" / f"{body}.json").read_text()))


def _list(seen: Row, key: str) -> list[Row]:
    return cast("list[Row]", seen[key])


def _part(parent: Row, key: str) -> Row:
    return cast("Row", parent[key])


async def _meeting(subject: str, day: str) -> Row:
    (found,) = _list(
        await _call("outlook_list_events", starts_on=day, ends_on=day, subject_contains=subject),
        "events",
    )
    return found


def _create_route(graph: respx.MockRouter) -> respx.Route:
    created = _recorded("rec-tool-outlook_create_event-simple.02")
    return graph.post("/me/events").mock(return_value=httpx.Response(201, json=created))


class TestAcceptingAnInvitation:
    async def test_an_accept_is_asked_first_and_recorded_once_it_is_approved(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_respond_to_invite-accept")
        roadmap = await _meeting("Roadmap check", "2026-10-29")
        mia = Person()

        seen = await call(
            "outlook_respond_to_invite", person=mia, uri=roadmap["uri"], response="accept"
        )

        assert [key for key, route in routes.items() if not route.called] == []
        assert "Accept 'Roadmap check'?" in mia.asked[0]
        assert (seen["response"], seen["sent_response"]) == ("accepted", True)


class TestAnsweringAnInvitation:
    @pytest.fixture
    def invitation(self, graph: respx.MockRouter) -> None:
        _stored(graph, _event(_LAUNCH, "Launch review", organizer=_ANNA, attendees=[_MIA]))

    async def test_a_decline_carries_the_note_to_the_organizer(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_respond_to_invite-decline")
        critique = await _meeting("Design critique", "2026-11-03")
        (decline,) = [route for (method, _path), route in routes.items() if method == "POST"]
        mia = Person()

        seen = await call(
            "outlook_respond_to_invite",
            person=mia,
            uri=critique["uri"],
            response="decline",
            comment="I am on leave",
        )

        assert "I am on leave" in mia.asked[0]
        assert _posted(decline)["Comment"] == "I am on leave"
        assert seen["response"] == "declined"

    async def test_a_new_time_is_proposed_when_the_organizer_allows_it(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_respond_to_invite-new-time")
        workshop = await _meeting("Workshop prep", "2026-11-03")
        (decline,) = [route for (method, _path), route in routes.items() if method == "POST"]
        mia = Person()

        seen = await call(
            "outlook_respond_to_invite",
            person=mia,
            uri=workshop["uri"],
            response="decline",
            proposed_new_time={
                "starts_at": "2026-11-09T10:00",
                "ends_at": "2026-11-09T10:30",
                "time_zone": _ZURICH,
            },
        )

        assert "2026-11-09T10:00" in mia.asked[0]
        slot = cast("Row", _posted(decline)["ProposedNewTime"])
        assert _part(slot, "start") == {"dateTime": "2026-11-09T10:00", "timeZone": _ZURICH}
        assert seen["response"] == "declined"

    async def test_a_new_time_is_not_proposed_when_the_organizer_allows_none(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_read_event-no-new-time")
        fixed = await _meeting("Fixed slot", "2026-11-03")
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_respond_to_invite",
                person=mia,
                uri=fixed["uri"],
                response="decline",
                proposed_new_time={
                    "starts_at": "2026-11-09T10:00",
                    "ends_at": "2026-11-09T10:30",
                    "time_zone": _ZURICH,
                },
            )

        assert "does not allow new time proposals" in str(refused.value)
        assert "remove `proposed_new_time`" in str(refused.value)
        assert (graph.calls.last.request.method, mia.asked) == ("GET", [])

    async def test_a_new_time_is_not_proposed_with_an_acceptance(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_respond_to_invite-accept")
        roadmap = await _meeting("Roadmap check", "2026-10-29")
        (accept,) = [route for (method, _path), route in routes.items() if method == "POST"]

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_respond_to_invite",
                uri=roadmap["uri"],
                response="accept",
                proposed_new_time={
                    "starts_at": "2026-11-09T10:00",
                    "ends_at": "2026-11-09T10:30",
                    "time_zone": _ZURICH,
                },
            )

        assert "use `decline` or `tentative`" in str(refused.value)
        assert accept.called is False

    @pytest.mark.usefixtures("invitation")
    async def test_a_withdrawn_invitation_records_no_answer_and_says_to_look_again(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_path(_LAUNCH)).mock(
            return_value=response({"status": 404, "body": "error.itemNotFound.json"})
        )
        accept = graph.post(f"{_path(_LAUNCH)}/accept").mock(return_value=httpx.Response(202))
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_respond_to_invite", person=mia, uri=_uri(_LAUNCH), response="accept"
            )

        assert "NO RESPONSE WAS RECORDED" in str(refused.value)
        assert "call outlook_list_events again" in str(refused.value)
        assert (accept.called, mia.asked) == (False, [])

    @pytest.mark.usefixtures("invitation")
    async def test_an_answer_that_microsoft_rejects_gives_the_reason_after_the_approval(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(f"{_path(_LAUNCH)}/accept").mock(
            return_value=httpx.Response(400, json=_REJECTION)
        )
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_respond_to_invite", person=mia, uri=_uri(_LAUNCH), response="accept"
            )

        assert len(mia.asked) == 1
        assert 'gave this reason: "The start is in the past."' in str(refused.value)
        assert "will fail the same way" in str(refused.value)

    async def test_every_invitation_of_a_leave_day_is_answered_one_at_a_time_each_with_a_question(
        self, graph: respx.MockRouter
    ) -> None:
        invited = [
            _event(_LAUNCH, "Launch review", organizer=_ANNA, attendees=[_MIA]),
            _event(_BUDGET, "Budget review", organizer=_TOM, attendees=[_MIA]),
        ]
        own = _event(_DESIGN, "Design review", attendees=[_ANNA])
        _stored(graph, *invited, own)
        _ = graph.get(f"/me/calendars/{_CALENDAR_ID}/calendarView").mock(
            return_value=httpx.Response(200, json={"value": [*invited, own]})
        )
        declines = {
            one: graph.post(f"{_path(one)}/decline").mock(return_value=httpx.Response(202))
            for one in (_LAUNCH, _BUDGET, _DESIGN)
        }
        mia = Person()

        day = await call(
            "outlook_list_events", starts_on="2026-11-06", ends_on="2026-11-06", time_zone=_ZURICH
        )
        for row in _list(day, "events"):
            if not row["owner_is_organizer"]:
                _ = await call(
                    "outlook_respond_to_invite",
                    person=mia,
                    uri=row["uri"],
                    response="decline",
                    comment="I am on leave",
                )

        assert len(mia.asked) == 2
        assert {one: route.called for one, route in declines.items()} == {
            _LAUNCH: True,
            _BUDGET: True,
            _DESIGN: False,
        }
        assert _posted(declines[_LAUNCH])["Comment"] == "I am on leave"


class TestListingTheInvitationsThatWait:
    async def test_it_lists_the_invitations_without_an_answer_and_not_the_accepted_ones(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_events-invitations-waiting")

        seen = await call(
            "outlook_list_events",
            starts_on="2026-11-02",
            ends_on="2026-11-03",
            owner_response="notResponded",
        )

        subjects = [one["subject"] for one in _list(seen, "events")]
        assert "Hosting standby" not in subjects
        assert subjects == [
            "Roadmap check",
            "Vendor call",
            "Design critique",
            "Planning session",
            "Workshop prep",
            "Fixed slot",
            "Leave day review 1",
            "Leave day review 2",
            "Leave day review 3",
            "Offsite forward target",
        ]


class TestAnEventWithNoAnswerOfMia:
    async def test_it_is_not_listed_as_an_invitation_that_waits(
        self, graph: respx.MockRouter
    ) -> None:
        unanswered = _event(_LAUNCH, "Launch review", organizer=_ANNA) | {"responseStatus": None}
        _ = graph.get("/me/calendar").mock(return_value=httpx.Response(200, json=_calendar()))
        _ = graph.get(f"/me/calendars/{_CALENDAR_ID}/calendarView").mock(
            return_value=httpx.Response(200, json={"value": [unanswered]})
        )

        seen = await call(
            "outlook_list_events",
            starts_on="2026-11-06",
            ends_on="2026-11-06",
            owner_response="notResponded",
        )

        assert _list(seen, "events") == []


def _schedule(address: str, view: str, **extra: object) -> dict[str, object]:
    return {"scheduleId": address, "availabilityView": view, "scheduleItems": [], **extra}


def _slot(start: str, end: str) -> dict[str, object]:
    return {
        "start": {"dateTime": f"{start}.0000000", "timeZone": _ZURICH},
        "end": {"dateTime": f"{end}.0000000", "timeZone": _ZURICH},
    }


async def _free_times(**arguments: object) -> Row:
    return await _call(
        "outlook_check_availability",
        **(
            {
                "addresses": ["anna@example.test"],
                "starts_at": "2026-11-02T08:00",
                "ends_at": "2026-11-02T18:00",
                "time_zone": _ZURICH,
            }
            | arguments
        ),
    )


class TestFindingATime:
    async def test_it_suggests_afternoon_times_when_both_colleagues_are_busy_in_the_morning(
        self, graph: respx.MockRouter
    ) -> None:
        busy_morning = "2222222200000000000"
        _ = graph.post("/me/calendar/getSchedule").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _schedule("anna@example.test", busy_morning),
                        _schedule("tom@example.test", busy_morning),
                    ]
                },
            )
        )
        _ = graph.post("/me/findMeetingTimes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "emptySuggestionsReason": "",
                    "meetingTimeSuggestions": [
                        {
                            "confidence": 100,
                            "meetingTimeSlot": _slot("2026-11-02T14:00:00", "2026-11-02T14:30:00"),
                        },
                        {
                            "confidence": 100,
                            "meetingTimeSlot": _slot("2026-11-02T15:00:00", "2026-11-02T15:30:00"),
                        },
                    ],
                },
            )
        )

        busy = await _free_times(addresses=["anna@example.test", "tom@example.test"])
        seen = await call(
            "outlook_suggest_meeting_times",
            attendees=["anna@example.test", "tom@example.test"],
            starts_at="2026-11-02T08:00",
            ends_at="2026-11-02T18:00",
            time_zone=_ZURICH,
            duration_minutes=30,
        )

        assert {one["availability_view"] for one in _list(busy, "schedules")} == {busy_morning}
        starts = [str(_part(one, "start")["local"]) for one in _list(seen, "suggestions")]
        assert starts == ["2026-11-02T14:00:00.0000000", "2026-11-02T15:00:00.0000000"]
        assert seen["empty_reason"] in (None, "")

    async def test_a_day_with_no_time_for_everyone_gives_no_suggestion_and_the_reason(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_suggest_meeting_times-nobody-free")

        seen = await call(
            "outlook_suggest_meeting_times",
            attendees=["anna@example.test", "tom@example.test"],
            starts_at="2026-11-02T08:00",
            ends_at="2026-11-02T18:00",
            time_zone=_ZURICH,
        )

        assert (seen["suggestions"], seen["empty_reason"]) == ([], "AttendeesUnavailable")

    async def test_a_colleague_who_is_free_is_shown_with_the_working_hours_to_compare_with(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_check_availability-colleague-free")

        seen = await _free_times(
            addresses=["tom@example.test"], starts_at="2026-11-03T13:00", ends_at="2026-11-03T15:00"
        )

        (tom,) = _list(seen, "schedules")
        assert tom["availability_view"] == "0" * 20
        assert tom["items"] == []
        hours = _part(tom, "working_hours")
        assert (hours["days"], str(hours["starts_at"])[:5], str(hours["ends_at"])[:5]) == (
            ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "07:00",
            "15:30",
        )

    @pytest.mark.parametrize(
        ("answer", "told"),
        [
            *_REFUSALS,
            pytest.param(
                None, 'gave this reason: "The start is in the past."', id="rejected-question"
            ),
        ],
    )
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_refused_search_for_free_times_is_explained_and_suggests_no_time(
        self, graph: respx.MockRouter, answer: Json | None, told: str
    ) -> None:
        refusal = _rejection() if answer is None else _reply(answer)
        _ = graph.post("/me/calendar/getSchedule").mock(side_effect=refusal)

        with pytest.raises(ToolError) as refused:
            _ = await _free_times()

        assert told in str(refused.value)
        assert "Retry once" not in str(refused.value)

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(
                _reply({"status": 500, "body": "error.generalException.json"}),
                id="fails",
            ),
            pytest.param(httpx.ReadTimeout, id="no-answer-in-time"),
        ],
    )
    async def test_a_search_that_microsoft_cannot_finish_is_not_reported_as_no_free_time(
        self, graph: respx.MockRouter, failure: Fault
    ) -> None:
        _ = graph.post("/me/calendar/getSchedule").mock(side_effect=failure)

        with pytest.raises(ToolError) as refused:
            _ = await _free_times()

        assert "Retry once; if it fails again the same way, stop and report it" in str(
            refused.value
        )

    async def test_one_busy_answer_is_waited_out_inside_the_same_call(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        _ = graph.post("/me/calendar/getSchedule").mock(
            side_effect=[
                response(_TOO_MANY),
                response(
                    {"status": 200, "body": "rec-tool-outlook_check_availability-tomorrow.04.json"}
                ),
            ]
        )

        seen = await _free_times()

        assert [one["address"] for one in _list(seen, "schedules")] == ["anna@example.test"]
        assert retry_sleeps.delays == [30]


async def _book(person: Person | None = None, **arguments: object) -> Row:
    return await _call(
        "outlook_create_event",
        person=person,
        **(
            {
                "subject": "Launch review",
                "time_zone": _ZURICH,
                "attendees": ["anna@example.test", "tom@example.test"],
            }
            | _MONDAY
            | arguments
        ),
    )


class TestBookingAMeeting:
    async def test_a_teams_meeting_is_asked_first_and_goes_out_to_each_attendee(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, _RECORDED_CREATE)
        mia = Person()

        _ = await _book(mia, online_meeting=True)

        assert "as a Teams meeting" in mia.asked[0]
        assert "anna@example.test, tom@example.test" in mia.asked[0]
        posted = _posted(routes[("POST", "/me/events")])
        assert posted["isOnlineMeeting"] is True
        assert [one["emailAddress"] for one in cast("list[Row]", posted["attendees"])] == [
            {"address": "anna@example.test"},
            {"address": "tom@example.test"},
        ]

    async def test_a_weekly_meeting_is_booked_in_one_call_as_one_series_of_eight(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, _RECORDED_CREATE)

        _ = await _book(
            attendees=[],
            subject="Stand-up",
            starts_at="2026-11-02T09:00",
            ends_at="2026-11-02T09:15",
            recurrence={
                "pattern_type": "weekly",
                "days_of_week": ["monday"],
                "range_type": "numbered",
                "number_of_occurrences": 8,
            },
        )

        create = routes[("POST", "/me/events")]
        assert create.call_count == 1
        rule = cast("Row", _posted(create)["recurrence"])
        assert _part(rule, "pattern")["type"] == "weekly"
        assert _part(rule, "range")["numberOfOccurrences"] == 8

    async def test_a_room_that_fits_the_group_is_invited_as_a_room(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, _RECORDED_CREATE)
        _ = graph.get("/places/graph.room").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "r1",
                            "displayName": "Birch",
                            "emailAddress": "birch@example.test",
                            "capacity": 4,
                        },
                        {
                            "id": "r2",
                            "displayName": "Maple",
                            "emailAddress": "maple@example.test",
                            "capacity": 8,
                        },
                    ]
                },
            )
        )

        rooms = await call("outlook_find_rooms", min_capacity=6)
        (maple,) = _list(rooms, "rooms")
        _ = await _book(Person(), subject="Workshop", room_addresses=[maple["address"]])

        resource = [
            one
            for one in cast("list[Row]", _posted(routes[("POST", "/me/events")])["attendees"])
            if one["type"] == "resource"
        ]
        assert [one["emailAddress"] for one in resource] == [{"address": "maple@example.test"}]

    async def test_an_invitation_to_finish_later_is_saved_with_no_attendee_and_no_question(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, _RECORDED_CREATE)
        mia = Person()

        seen = await _book(
            mia,
            subject="Board prep",
            attendees=[],
            starts_at="2026-11-02T10:00",
            ends_at="2026-11-02T11:00",
        )

        assert mia.asked == []
        assert _posted(routes[("POST", "/me/events")]).get("attendees", []) == []
        assert seen["invitations_sent"] is False

    async def test_a_meeting_on_a_second_calendar_of_mia_is_not_put_on_the_main_one(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_create_event_on_behalf-shared-calendar")
        calendars = await call("outlook_list_calendars")
        second = next(one for one in _list(calendars, "calendars") if not one["is_default"])

        _ = await call(
            "outlook_create_event_on_behalf",
            person=Person(),
            calendar_ref=second["uri"],
            subject="Offsite",
            attendees=[],
            time_zone=_ZURICH,
            **_MONDAY,
        )

        second_id = unquote(str(second["uri"]).rsplit("/", 1)[1])
        reached = [path for (method, path), r in routes.items() if method == "POST" and r.called]
        assert reached == [f"/me/calendars/{second_id}/events"]

    async def test_a_day_is_blocked_as_out_of_office_with_no_question_and_no_invitation(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, _RECORDED_CREATE)
        mia = Person()

        _ = await call(
            "outlook_create_event",
            person=mia,
            subject="Out of office",
            attendees=[],
            starts_at="2026-11-06T00:00",
            ends_at="2026-11-07T00:00",
            time_zone=_ZURICH,
            all_day=True,
            show_as="oof",
        )

        posted = _posted(routes[("POST", "/me/events")])
        assert mia.asked == []
        assert (posted["isAllDay"], posted["showAs"]) == (True, "oof")
        assert posted.get("attendees", []) == []

    async def test_a_meeting_that_ends_before_it_starts_is_not_booked(
        self, graph: respx.MockRouter
    ) -> None:
        create = _create_route(graph)
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _book(mia, starts_at="2026-11-02T15:00", ends_at="2026-11-02T14:00")

        assert "NO EVENT WAS CREATED and nobody was invited" in str(refused.value)
        assert (create.called, mia.asked, graph.calls.call_count) == (False, [], 0)

    async def test_a_teams_meeting_on_a_calendar_that_takes_none_is_refused_and_then_booked_without(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, _RECORDED_CREATE)
        takes_none = _recorded("rec-tool-outlook_create_event-simple.01") | {
            "allowedOnlineMeetingProviders": ["unknown"],
            "defaultOnlineMeetingProvider": "unknown",
        }
        _ = routes[("GET", "/me/calendar")].mock(return_value=httpx.Response(200, json=takes_none))
        create = routes[("POST", "/me/events")]
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _book(mia, online_meeting=True)

        assert "does not take one" in str(refused.value)
        assert "call again with `online_meeting` off" in str(refused.value)
        assert (create.called, mia.asked) == (False, [])
        _ = await _book(mia, online_meeting=False)
        assert create.called
        assert _posted(create).get("isOnlineMeeting") in (None, False)
        assert "Teams meeting" not in mia.asked[0]

    async def test_a_meeting_at_the_time_of_another_city_is_booked_in_that_zone(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, _RECORDED_CREATE)
        _ = serve(graph, "rec-tool-outlook_list_time_zones-windows")

        zones = await call("outlook_list_time_zones")
        (mumbai,) = [one for one in _list(zones, "time_zones") if one["alias"] == _MUMBAI]
        _ = await _book(
            Person(),
            attendees=["priya@example.test"],
            time_zone=str(mumbai["alias"]),
            starts_at="2026-11-02T15:00",
            ends_at="2026-11-02T15:30",
        )

        assert _part(_posted(routes[("POST", "/me/events")]), "start") == {
            "dateTime": "2026-11-02T15:00",
            "timeZone": _MUMBAI,
        }

    @pytest.mark.parametrize(
        ("answer", "told"),
        [
            *_REFUSALS,
            pytest.param(
                None, 'gave this reason: "The start is in the past."', id="rejected-booking"
            ),
        ],
    )
    async def test_a_booking_that_microsoft_refuses_is_explained_and_creates_nothing(
        self, graph: respx.MockRouter, answer: Json | None, told: str
    ) -> None:
        routes = serve(graph, _RECORDED_CREATE)
        create = routes[("POST", "/me/events")].mock(
            side_effect=_rejection() if answer is None else _reply(answer)
        )

        with pytest.raises(ToolError) as refused:
            _ = await _book()

        assert told in str(refused.value)
        assert create.call_count == 1

    async def test_a_booking_that_microsoft_cannot_serve_now_may_exist_and_is_not_repeated(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, _RECORDED_CREATE)
        create = routes[("POST", "/me/events")].mock(
            return_value=httpx.Response(503, headers={"Retry-After": "30"})
        )

        with pytest.raises(ToolError) as refused:
            _ = await _book()

        assert "asked to be left alone for 30 seconds" in str(refused.value)
        assert "No event was created" not in str(refused.value)
        assert create.call_count == 1


def _stored_changeable(graph: respx.MockRouter) -> None:
    _stored(
        graph,
        _event(_DESIGN, "Design review", attendees=[_ANNA], start="2026-10-31T09:00:00"),
        _event(_LAUNCH, "Launch review", organizer=_ANNA, attendees=[_MIA]),
        _event(
            _SYNC,
            "Team sync",
            attendees=[_ANNA],
            kind="occurrence",
            series=_SERIES,
            start="2026-11-05T09:00:00",
        ),
        _event(
            _SERIES,
            "Team sync",
            attendees=[_ANNA, _TOM],
            kind="seriesMaster",
            start="2026-11-05T09:00:00",
        ),
        _event(_BUDGET, "Budget review", attendees=[_TOM]),
    )


class TestChangingOrCancellingAMeeting:
    @pytest.fixture
    def meetings(self, graph: respx.MockRouter) -> None:
        _stored_changeable(graph)

    @pytest.mark.usefixtures("meetings")
    async def test_one_date_of_a_series_moves_and_the_series_is_left_alone(
        self, graph: respx.MockRouter
    ) -> None:
        occurrence = graph.patch(_path(_SYNC)).mock(
            return_value=httpx.Response(
                200,
                json=_event(
                    _SYNC, "Team sync", attendees=[_ANNA], kind="occurrence", series=_SERIES
                ),
            )
        )
        master = graph.patch(_path(_SERIES)).mock(return_value=httpx.Response(200, json={}))
        mia = Person()

        _ = await call(
            "outlook_update_event",
            person=mia,
            uri=_uri(_SYNC),
            starts_at="2026-11-06T10:00",
            ends_at="2026-11-06T10:30",
            time_zone=_ZURICH,
        )

        assert mia.asked
        assert _part(_posted(occurrence), "start") == {
            "dateTime": "2026-11-06T10:00",
            "timeZone": _ZURICH,
        }
        assert master.called is False

    @pytest.mark.usefixtures("meetings")
    async def test_a_whole_series_is_cancelled_after_the_question_and_the_attendees_are_told(
        self, graph: respx.MockRouter
    ) -> None:
        cancel = graph.post(f"{_path(_SERIES)}/cancel").mock(return_value=httpx.Response(202))
        mia = Person()

        seen = await call("outlook_cancel_event", person=mia, uri=_uri(_SERIES))

        assert "every occurrence" in mia.asked[0]
        assert cancel.called
        assert (seen["series_master"], seen["notified"]) == (True, True)
        assert [one["address"] for one in _list(seen, "attendees")] == [
            "anna@example.test",
            "tom@example.test",
        ]

    async def test_a_person_is_added_to_a_meeting_and_the_others_stay(
        self, graph: respx.MockRouter
    ) -> None:
        _stored(graph, _event(_LAUNCH, "Launch review", attendees=[_ANNA, _TOM]))
        patch = graph.patch(_path(_LAUNCH)).mock(
            return_value=httpx.Response(
                200, json=_event(_LAUNCH, "Launch review", attendees=[_ANNA, _TOM, _PRIYA])
            )
        )
        mia = Person()

        _ = await call(
            "outlook_update_event",
            person=mia,
            uri=_uri(_LAUNCH),
            attendees=["anna@example.test", "tom@example.test", "priya@example.test"],
            optional_attendees=[],
        )

        assert "priya@example.test" in mia.asked[0]
        invited = [one["emailAddress"] for one in cast("list[Row]", _posted(patch)["attendees"])]
        assert [one["address"] for one in cast("list[Row]", invited)] == [
            "anna@example.test",
            "tom@example.test",
            "priya@example.test",
        ]

    @pytest.mark.parametrize(
        ("tool", "arguments", "write", "told"),
        [
            pytest.param(
                "outlook_update_event",
                {
                    "starts_at": "2026-11-06T10:00",
                    "ends_at": "2026-11-06T10:30",
                    "time_zone": _ZURICH,
                },
                ("PATCH", ""),
                "outlook_respond_to_invite can accept, decline",
                id="move",
            ),
            pytest.param(
                "outlook_cancel_event",
                {},
                ("POST", "/cancel"),
                "only the organizer can cancel it",
                id="cancel",
            ),
            pytest.param(
                "outlook_delete_event",
                {},
                ("DELETE", ""),
                "outlook_respond_to_invite can decline",
                id="delete",
            ),
        ],
    )
    async def test_a_meeting_of_another_organizer_is_neither_changed_nor_asked_about(
        self,
        graph: respx.MockRouter,
        tool: str,
        arguments: Row,
        write: tuple[str, str],
        told: str,
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_respond_to_invite-decline")
        critique = await _meeting("Design critique", "2026-11-03")
        calendar_id, event_id = (unquote(one) for one in str(critique["uri"]).split("/")[-2:])
        changed = graph.route(
            method=write[0], path=f"/me/calendars/{calendar_id}/events/{event_id}{write[1]}"
        ).mock(return_value=httpx.Response(202))
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, person=mia, uri=critique["uri"], **arguments)

        assert told in str(refused.value)
        assert (changed.called, mia.asked) == (False, [])

    @pytest.mark.parametrize(
        ("tool", "arguments", "told"),
        [
            pytest.param(
                "outlook_update_event", {"subject": "Moved"}, "NOTHING WAS CHANGED", id="move"
            ),
            pytest.param("outlook_delete_event", {}, "this call deleted nothing", id="delete"),
        ],
    )
    @pytest.mark.usefixtures("meetings")
    async def test_a_meeting_that_is_gone_is_not_changed_or_deleted_and_the_advice_is_to_look_again(
        self, graph: respx.MockRouter, tool: str, arguments: Row, told: str
    ) -> None:
        _ = graph.get(_path(_DESIGN)).mock(
            return_value=response({"status": 404, "body": "error.itemNotFound.json"})
        )
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, person=mia, uri=_uri(_DESIGN), **arguments)

        assert told in str(refused.value)
        assert "outlook_list_events again" in str(refused.value)
        assert mia.asked == []

    async def test_a_deleted_meeting_is_asked_about_by_name_and_attendee_and_then_removed(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_delete_event-with-attendee")
        booked = await _call(
            "outlook_create_event",
            person=Person(),
            subject="Budget alignment",
            attendees=["anna@example.test"],
            time_zone=_ZURICH,
            **_MONDAY,
        )
        mia = Person()

        seen = await call("outlook_delete_event", person=mia, uri=booked["uri"])

        assert "case-outlook_delete_event-with-attendee" in mia.asked[0]
        assert "anna@example.test" in mia.asked[0]
        assert routes[next(key for key in routes if key[0] == "DELETE")].called
        assert [one["address"] for one in _list(seen, "attendees")] == ["anna@example.test"]


class TestCancellingAMeetingWithANote:
    async def test_a_meeting_is_cancelled_with_a_note_for_the_attendee(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_cancel_event-budget")
        budget = await _meeting("Budget alignment", "2026-10-30")
        mia = Person()

        seen = await call(
            "outlook_cancel_event",
            person=mia,
            uri=budget["uri"],
            comment="The numbers are not final.",
        )

        (cancel,) = [route for (method, _path), route in routes.items() if method == "POST"]
        assert [key for key, route in routes.items() if not route.called] == []
        assert "anna@example.test" in mia.asked[0]
        assert "The numbers are not final." in mia.asked[0]
        assert _posted(cancel) == {"Comment": "The numbers are not final."}
        assert (seen["comment"], seen["notified"]) == ("The numbers are not final.", True)


class TestForwardingAnInvitation:
    async def test_an_invitation_is_forwarded_with_the_note_and_the_organizer_is_told(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_forward_event-received")
        offsite = await _meeting("Offsite forward target", "2026-11-03")
        (forward,) = [route for (method, _path), route in routes.items() if method == "POST"]
        mia = Person()

        seen = await call(
            "outlook_forward_event",
            person=mia,
            uri=offsite["uri"],
            to=["priya@example.test"],
            comment="Please join",
        )

        assert "priya@example.test" in mia.asked[0]
        assert _posted(forward)["Comment"] == "Please join"
        assert _posted(forward)["ToRecipients"] == [
            {"emailAddress": {"address": "priya@example.test"}}
        ]
        assert seen["organizer_notified"] is True

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(_reply({"status": 504}), id="fails"),
            pytest.param(httpx.ReadTimeout, id="no-answer-in-time"),
        ],
    )
    async def test_a_forward_that_microsoft_fails_is_not_repeated_and_the_user_is_asked_to_check(
        self, graph: respx.MockRouter, failure: Fault
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_forward_event-hosting")
        hosting = await _meeting("Hosting review", "2026-10-29")
        (forward,) = [route for (method, _path), route in routes.items() if method == "POST"]
        _ = forward.mock(side_effect=failure)

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_forward_event", uri=hosting["uri"], to=["priya@example.test"])

        assert "does not know if Microsoft 365 made the change" in str(refused.value)
        assert "Do not call this tool again first" in str(refused.value)
        assert "ask the user if the Microsoft 365 app shows the change" in str(refused.value)
        assert forward.call_count == 1


class TestARoomList:
    async def test_a_room_list_that_microsoft_does_not_know_is_reported_with_the_way_on(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="GET", path__startswith="/places/building9").mock(
            return_value=response({"status": 404, "body": "error.itemNotFound.json"})
        )

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_find_rooms", room_list="building9@example.com")

        assert "Microsoft found no room list at that address" in str(refused.value)
        assert "call this tool again without `room_list`" in str(refused.value)

    async def test_a_name_in_place_of_the_address_of_a_room_list_reads_nothing(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_find_rooms", room_list="Building 9")

        assert "takes one SMTP address in `room_list`" in str(refused.value)
        assert graph.calls.call_count == 0


class TestTheTimeZonesInTheNamesOfAListing:
    async def test_the_iana_names_are_asked_for_in_the_form_that_microsoft_documents(
        self, graph: respx.MockRouter
    ) -> None:
        zones = graph.route(method="GET", path__startswith="/me/outlook/supportedTimeZones").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {"alias": "Europe/Zurich", "displayName": "Europe/Zurich"},
                        {"alias": "Asia/Kolkata", "displayName": "Asia/Kolkata"},
                    ]
                },
            )
        )

        listed = await call("outlook_list_time_zones", standard="iana")

        assert [one["alias"] for one in _list(listed, "time_zones")] == [
            "Europe/Zurich",
            "Asia/Kolkata",
        ]
        assert "microsoft.graph.timeZoneStandard'Iana'" in zones.calls.last.request.url.path


_BOOK: Row = {
    "subject": "Launch review",
    "time_zone": _ZURICH,
    "attendees": ["anna@example.test", "tom@example.test"],
}

_APPROVAL_ROWS = [
    pytest.param(
        "outlook_create_event",
        _BOOK | _MONDAY,
        _BOOK | {"starts_at": "2026-11-03T14:00", "ends_at": "2026-11-03T14:30"},
        id="book",
    ),
    pytest.param(
        "outlook_respond_to_invite",
        {"uri": _uri(_LAUNCH), "response": "decline", "comment": "I am on leave"},
        {"uri": _uri(_LAUNCH), "response": "accept"},
        id="decline",
    ),
    pytest.param(
        "outlook_cancel_event", {"uri": _uri(_DESIGN)}, {"uri": _uri(_BUDGET)}, id="cancel"
    ),
    pytest.param(
        "outlook_update_event",
        {
            "uri": _uri(_SYNC),
            "starts_at": "2026-11-06T10:00",
            "ends_at": "2026-11-06T10:30",
            "time_zone": _ZURICH,
        },
        {
            "uri": _uri(_SYNC),
            "starts_at": "2026-11-07T10:00",
            "ends_at": "2026-11-07T10:30",
            "time_zone": _ZURICH,
        },
        id="move",
    ),
    pytest.param(
        "outlook_forward_event",
        {"uri": _uri(_LAUNCH), "to": ["priya@example.test"]},
        {"uri": _uri(_LAUNCH), "to": ["sam@example.test"]},
        id="forward",
    ),
    pytest.param(
        "outlook_delete_event", {"uri": _uri(_DESIGN)}, {"uri": _uri(_BUDGET)}, id="delete"
    ),
]


def _writable(graph: respx.MockRouter) -> list[respx.Route]:
    _stored_changeable(graph)
    created = _recorded("rec-tool-outlook_create_event-simple.02")
    return [
        graph.post("/me/events").mock(return_value=httpx.Response(201, json=created)),
        graph.post(f"{_path(_LAUNCH)}/decline").mock(return_value=httpx.Response(202)),
        graph.post(f"{_path(_LAUNCH)}/accept").mock(return_value=httpx.Response(202)),
        graph.post(f"{_path(_DESIGN)}/cancel").mock(return_value=httpx.Response(202)),
        graph.post(f"{_path(_BUDGET)}/cancel").mock(return_value=httpx.Response(202)),
        graph.patch(_path(_SYNC)).mock(
            return_value=httpx.Response(200, json=_event(_SYNC, "Team sync"))
        ),
        graph.post(f"{_path(_LAUNCH)}/forward").mock(return_value=httpx.Response(202)),
        graph.delete(_path(_DESIGN)).mock(return_value=httpx.Response(204)),
        graph.delete(_path(_BUDGET)).mock(return_value=httpx.Response(204)),
    ]


class TestNothingIsDoneWithoutAnApproval:
    @pytest.mark.parametrize(("tool", "arguments", "_other"), _APPROVAL_ROWS)
    async def test_an_approval_that_mia_refuses_changes_nothing_and_says_it_was_not_confirmed(
        self, graph: respx.MockRouter, tool: str, arguments: Row, _other: Row
    ) -> None:
        writes = _writable(graph)
        mia = Person(approval="no")

        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, person=mia, **arguments)

        assert len(mia.asked) == 1
        assert "say that the request was not confirmed" in str(refused.value)
        assert "Do not call this tool again for the same request unless the user asks" in str(
            refused.value
        )
        assert [route for route in writes if route.called] == []

    @pytest.mark.parametrize(("tool", "arguments", "_other"), _APPROVAL_ROWS)
    async def test_an_approval_question_that_gets_no_answer_changes_nothing(
        self, graph: respx.MockRouter, tool: str, arguments: Row, _other: Row
    ) -> None:
        writes = _writable(graph)

        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, person=Person(approval="unanswered"), **arguments)

        assert "received no answer" in str(refused.value)
        assert "make the same request again" in str(refused.value)
        assert [route for route in writes if route.called] == []

    @pytest.mark.parametrize(("tool", "approved", "attempted"), _APPROVAL_ROWS)
    async def test_an_approval_for_one_request_does_not_cover_another(
        self, graph: respx.MockRouter, tool: str, approved: Row, attempted: Row
    ) -> None:
        writes = _writable(graph)
        with pytest.MonkeyPatch.context() as patch:
            patch_obo(patch)
            async with Client(FastMCPTransport(build_server())) as client:
                first = await client.session.call_tool(
                    tool, dict(approved), allow_input_required=True
                )
                assert isinstance(first, InputRequiredResult)
                ((key, asked),) = (first.input_requests or {}).items()
                form = cast("ElicitRequestFormParams", cast("ElicitRequest", asked).params)
                yes = cast("list[str]", form.requested_schema["properties"]["value"]["enum"])[0]
                carried: dict[str, InputResponse] = {
                    key: CarriedAnswer(action="accept", content={"value": yes})
                }
                with pytest.raises(MCPError, match="requestState"):
                    _ = await client.session.call_tool(
                        tool,
                        dict(attempted),
                        input_responses=carried,
                        request_state=first.request_state,
                        allow_input_required=True,
                    )
                without_state = await client.session.call_tool(
                    tool, dict(attempted), input_responses=carried, allow_input_required=True
                )

        assert isinstance(without_state, CallToolResult)
        refusal = " ".join(b.text for b in without_state.content if isinstance(b, TextContent))
        assert without_state.is_error
        assert "given for a different request" in refusal
        assert [route for route in writes if route.called] == []


_LENA_URI = "outlook:///calendars/AAMkSYNTHETIC-calendar-lena"
_ROOM = "room-pilatus@example.test"
_ONLINE = {
    "isOnlineMeeting": True,
    "onlineMeeting": {"joinUrl": "https://teams.example.test/join"},
    "body": {
        "contentType": "html",
        "content": "<html><body><p>Join the meeting</p></body></html>",
    },
}
_BOOKING_TOOLS = {
    "outlook_create_event": {},
    "outlook_create_event_on_behalf": {"calendar_ref": _LENA_URI},
}
_TAKES_NO_TEAMS = {"allowedOnlineMeetingProviders": ["unknown"]}


def _weekly(**rule: object) -> Row:
    return {"recurrence": {"pattern_type": "weekly", "days_of_week": ["monday"]} | rule}


_BAD_BOOKINGS = [
    pytest.param(
        {"starts_at": "2026-11-02T14:00+01:00"},
        ("carries a time zone of its own", "not a local wall-clock time"),
        id="offset-in-the-time",
    ),
    pytest.param(
        {"starts_at": "Monday at 2"},
        ("not a time it can read", "not a local wall-clock time"),
        id="words-for-the-time",
    ),
    pytest.param(
        {"starts_at": "2026-02-30T14:00"},
        ("not a time it can read", "not a local wall-clock time"),
        id="a-date-that-does-not-exist",
    ),
    pytest.param(
        {"ends_at": "2026-11-02T13:00"},
        ("not after `starts_at`", "at or before `starts_at`"),
        id="ends-before-it-starts",
    ),
    pytest.param(
        {"all_day": True},
        ("midnight on both ends", "midnight to midnight"),
        id="all-day-not-at-midnight",
    ),
    pytest.param(
        {"attendees": ["Anna Meier"]},
        ("is not one email address", "is not one email address"),
        id="a-name-for-an-address",
    ),
    pytest.param(
        {"attendees": ["anna@example.test", "ANNA@example.test"]},
        ("twice in `attendees`", "more than once in `attendees`"),
        id="one-person-twice",
    ),
    pytest.param(
        {"attendees": ["anna@example.test"], "optional_attendees": ["anna@example.test"]},
        ("in both `attendees` and `optional_attendees`", "the same address in `attendees`"),
        id="one-person-in-both-lists",
    ),
    pytest.param(
        {"attendees": [_ROOM], "room_addresses": [_ROOM]},
        ("in `room_addresses` and also in", "in `room_addresses` that is also in"),
        id="a-room-as-a-person",
    ),
    pytest.param(
        _weekly(range_type="noEnd", days_of_week=[]),
        ("needs `days_of_week`", "needs `days_of_week`"),
        id="weekly-with-no-day",
    ),
    pytest.param(
        {
            "recurrence": {
                "pattern_type": "daily",
                "days_of_week": ["monday"],
                "range_type": "noEnd",
            }
        },
        ("takes no `days_of_week`", "takes no `days_of_week`"),
        id="daily-with-a-day",
    ),
    pytest.param(
        _weekly(range_type="numbered"),
        ("needs `number_of_occurrences`", "needs `number_of_occurrences`"),
        id="a-count-with-no-number",
    ),
    pytest.param(
        _weekly(range_type="noEnd", end_date="2026-12-01"),
        ("takes no `end_date`", "takes no `end_date`"),
        id="no-end-with-an-end-date",
    ),
    pytest.param(
        _weekly(range_type="endDate", end_date="2026-10-01"),
        ("is before 2026-11-02", "is before 2026-11-02"),
        id="an-end-date-before-the-start",
    ),
]

_BOOKING_QUESTIONS = [
    pytest.param(
        {"all_day": True, "starts_at": "2026-11-02T00:00", "ends_at": "2026-11-03T00:00"},
        "as an all-day event on 2026-11-02",
        id="one-whole-day",
    ),
    pytest.param(
        {"all_day": True, "starts_at": "2026-11-02T00:00", "ends_at": "2026-11-05T00:00"},
        "as an all-day event from 2026-11-02 to 2026-11-04",
        id="three-whole-days",
    ),
    pytest.param(
        {
            "recurrence": {
                "pattern_type": "daily",
                "interval": 2,
                "range_type": "endDate",
                "end_date": "2026-11-10",
            }
        },
        "repeating every 2 days until 2026-11-10",
        id="every-second-day",
    ),
    pytest.param(
        _weekly(
            days_of_week=["monday", "wednesday", "friday"],
            first_day_of_week="monday",
            range_type="noEnd",
        ),
        "repeating every week on Monday, Wednesday, and Friday (weeks start on Monday) with no end",
        id="three-days-a-week",
    ),
    pytest.param(
        {
            "recurrence": {
                "pattern_type": "absoluteMonthly",
                "day_of_month": 15,
                "range_type": "numbered",
                "number_of_occurrences": 1,
            }
        },
        "repeating every month on day 15, 1 time",
        id="a-day-of-the-month",
    ),
    pytest.param(
        {
            "recurrence": {
                "pattern_type": "relativeMonthly",
                "days_of_week": ["tuesday"],
                "index": "second",
                "range_type": "numbered",
                "number_of_occurrences": 3,
            }
        },
        "repeating every month on the second Tuesday, 3 times",
        id="a-weekday-of-the-month",
    ),
    pytest.param(
        {
            "recurrence": {
                "pattern_type": "absoluteYearly",
                "day_of_month": 5,
                "month": 3,
                "range_type": "noEnd",
            }
        },
        "repeating every year on March 5 with no end",
        id="a-day-of-the-year",
    ),
    pytest.param(
        {
            "recurrence": {
                "pattern_type": "relativeYearly",
                "days_of_week": ["thursday", "friday"],
                "index": "fourth",
                "month": 11,
                "range_type": "noEnd",
            }
        },
        "repeating every year on the fourth Thursday or Friday of November with no end",
        id="a-weekday-of-the-year",
    ),
    pytest.param(
        {"reminder_minutes_before_start": 1},
        "with a reminder 1 minute before the start",
        id="a-reminder-time",
    ),
    pytest.param(
        {"is_reminder_on": False, "reminder_minutes_before_start": 15},
        "with no reminder, and a reminder time of 15 minutes before the start",
        id="no-reminder-and-a-time",
    ),
    pytest.param(
        {"hide_attendees": True, "response_requested": False, "allow_new_time_proposals": True},
        "with the attendee list hidden, with no response requested, with new time proposals",
        id="settings-for-the-attendees",
    ),
    pytest.param(
        {"body": "Agenda"},
        "with a body of",
        id="a-body",
    ),
]


class TestABookingThatCannotBeRead:
    @pytest.mark.parametrize("tool", _BOOKING_TOOLS)
    @pytest.mark.parametrize(("arguments", "told"), _BAD_BOOKINGS)
    async def test_it_books_nothing_and_asks_nothing_and_says_what_to_correct(
        self, graph: respx.MockRouter, tool: str, arguments: Row, told: tuple[str, str]
    ) -> None:
        mia = Person()
        booking: dict[str, object] = {
            "subject": "Launch review",
            "time_zone": _ZURICH,
            "attendees": ["anna@example.test"],
            **_MONDAY,
            **_BOOKING_TOOLS[tool],
            **arguments,
        }

        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, person=mia, **booking)

        assert told[tool == "outlook_create_event_on_behalf"] in str(refused.value)
        assert "NO EVENT WAS CREATED and nobody was invited" in str(refused.value)
        assert (mia.asked, graph.calls.call_count) == ([], 0)

    async def test_a_calendar_link_that_is_not_one_books_nothing(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _call(
                "outlook_create_event_on_behalf",
                calendar_ref="Lena Frei",
                subject="Budget review",
                time_zone=_ZURICH,
                attendees=[],
                **_MONDAY,
            )

        assert "takes the `calendar_ref` handle" in str(refused.value)
        assert graph.calls.call_count == 0


class TestWhatMiaIsToldBeforeABooking:
    @pytest.mark.parametrize(("arguments", "told"), _BOOKING_QUESTIONS)
    async def test_the_question_names_every_detail_of_the_booking(
        self, graph: respx.MockRouter, arguments: Row, told: str
    ) -> None:
        _ = serve(graph, _RECORDED_CREATE)
        mia = Person(approval="no")

        with pytest.raises(ToolError):
            _ = await _book(mia, location="Room Pilatus", **arguments)

        assert told in mia.asked[0]

    @pytest.mark.parametrize(
        ("arguments", "told"),
        [
            pytest.param(
                {"room_addresses": [_ROOM]}, "Microsoft sends the meeting request", id="a-room"
            ),
            pytest.param({}, "No person is invited", id="a-place"),
        ],
    )
    async def test_a_booking_with_a_room_or_a_place_and_nobody_else_says_nobody_is_invited(
        self, graph: respx.MockRouter, arguments: Row, told: str
    ) -> None:
        _ = serve(graph, _RECORDED_CREATE)
        mia = Person(approval="no")

        with pytest.raises(ToolError):
            _ = await _book(mia, attendees=[], location="Room Pilatus", **arguments)

        assert told in mia.asked[0]


class TestABookingForSomebodyElseWithNobodyInvited:
    @pytest.fixture
    def lena(self, graph: respx.MockRouter) -> None:
        shown = {
            "id": "AAMkSYNTHETIC-calendar-lena",
            "name": "Lena Frei",
            "owner": None,
            "canEdit": True,
            "allowedOnlineMeetingProviders": ["teamsForBusiness"],
        }
        _ = graph.get("/me/calendars/AAMkSYNTHETIC-calendar-lena").mock(
            return_value=httpx.Response(200, json=shown)
        )

    @pytest.mark.usefixtures("lena")
    @pytest.mark.parametrize(
        ("arguments", "told"),
        [
            pytest.param({"room_addresses": [_ROOM]}, "mailbox of each room", id="a-room"),
            pytest.param({"location": "Room Pilatus"}, "No person is invited", id="a-place"),
            pytest.param({}, "There are no invitations", id="nothing"),
        ],
    )
    async def test_the_question_says_who_is_told_and_names_no_owner_when_microsoft_gives_none(
        self, arguments: Row, told: str
    ) -> None:
        mia = Person(approval="no")

        with pytest.raises(ToolError):
            _ = await _call(
                "outlook_create_event_on_behalf",
                person=mia,
                calendar_ref=_LENA_URI,
                subject="Budget review",
                time_zone=_ZURICH,
                attendees=[],
                **_MONDAY,
                **arguments,
            )

        assert told in mia.asked[0]
        assert "the person who owns that calendar" in mia.asked[0]

    @pytest.mark.usefixtures("lena")
    async def test_a_calendar_that_takes_no_teams_meeting_gets_none_and_the_way_on_is_named(
        self, graph: respx.MockRouter
    ) -> None:
        shown = {
            "id": "AAMkSYNTHETIC-calendar-lena",
            "name": "Lena Frei",
            "owner": {"name": "Lena Frei", "address": "lena@example.test"},
            "canEdit": True,
        } | _TAKES_NO_TEAMS
        _ = graph.get("/me/calendars/AAMkSYNTHETIC-calendar-lena").mock(
            return_value=httpx.Response(200, json=shown)
        )

        with pytest.raises(ToolError) as refused:
            _ = await _call(
                "outlook_create_event_on_behalf",
                calendar_ref=_LENA_URI,
                subject="Budget review",
                time_zone=_ZURICH,
                attendees=["anna@example.test"],
                online_meeting=True,
                **_MONDAY,
            )

        assert "takes no Microsoft Teams meeting" in str(refused.value)
        assert "unknown" in str(refused.value)


_BAD_SEARCHES = [
    pytest.param(
        {"starts_at": "tomorrow"},
        "is not a local wall-clock time",
        "is not a local wall-clock time",
        id="words-for-the-time",
    ),
    pytest.param(
        {"ends_at": "2026-11-02T07:00"},
        "is not after `starts_at`",
        "is not after `starts_at`",
        id="ends-before-it-starts",
    ),
    pytest.param(
        {"attendees": ["Anna Meier"]},
        "is not one email address",
        "is not one email address",
        id="a-name-for-an-address",
    ),
    pytest.param(
        {"attendees": ["anna@example.test", "Anna@example.test"]},
        "twice in `addresses`",
        "twice in `attendees`",
        id="one-person-twice",
    ),
]


class TestASearchForFreeTimeThatCannotBeRead:
    @pytest.mark.parametrize(("arguments", "checks", "suggests"), _BAD_SEARCHES)
    @pytest.mark.parametrize(
        "tool", ["outlook_check_availability", "outlook_suggest_meeting_times"]
    )
    async def test_it_reads_no_calendar_and_says_what_to_correct(
        self,
        graph: respx.MockRouter,
        tool: str,
        arguments: Row,
        checks: str,
        suggests: str,
    ) -> None:
        window = {"starts_at": "2026-11-02T08:00", "ends_at": "2026-11-02T18:00"}
        people = "addresses" if tool == "outlook_check_availability" else "attendees"
        base: dict[str, object] = {people: ["anna@example.test"], "time_zone": _ZURICH, **window}
        given = base | {
            people if key == "attendees" else key: value for key, value in arguments.items()
        }

        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, **given)

        assert (checks if people == "addresses" else suggests) in str(refused.value)
        assert graph.calls.call_count == 0

    async def test_a_person_named_as_needed_and_as_optional_is_refused(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _call(
                "outlook_suggest_meeting_times",
                attendees=["anna@example.test"],
                optional_attendees=["anna@example.test"],
                starts_at="2026-11-02T08:00",
                ends_at="2026-11-02T18:00",
                time_zone=_ZURICH,
            )

        assert "in both `attendees` and `optional_attendees`" in str(refused.value)
        assert graph.calls.call_count == 0

    async def test_a_room_that_is_not_an_address_is_refused(self, graph: respx.MockRouter) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _call(
                "outlook_suggest_meeting_times",
                attendees=["anna@example.test"],
                starts_at="2026-11-02T08:00",
                ends_at="2026-11-02T18:00",
                time_zone=_ZURICH,
                location_constraint={
                    "locations": [{"display_name": "Pilatus", "address": "Pilatus"}]
                },
            )

        assert "location_constraint.locations[].address" in str(refused.value)
        assert graph.calls.call_count == 0

    async def test_a_room_asked_for_is_sent_and_the_rooms_that_microsoft_names_are_shown(
        self, graph: respx.MockRouter
    ) -> None:
        found = graph.post("/me/findMeetingTimes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "emptySuggestionsReason": "",
                    "meetingTimeSuggestions": [
                        {
                            "confidence": 100,
                            "meetingTimeSlot": _slot("2026-11-02T14:00:00", "2026-11-02T14:30:00"),
                            "locations": [
                                {"displayName": "Room Pilatus", "locationEmailAddress": _ROOM}
                            ],
                        },
                    ],
                },
            )
        )

        seen = await call(
            "outlook_suggest_meeting_times",
            attendees=["anna@example.test"],
            starts_at="2026-11-02T08:00",
            ends_at="2026-11-02T18:00",
            time_zone=_ZURICH,
            location_constraint={
                "is_required": True,
                "suggest_location": True,
                "locations": [
                    {"display_name": "Room Pilatus", "address": f" {_ROOM} "},
                    {"display_name": "Any room on floor 2"},
                ],
            },
        )

        sent = cast("Row", _posted(found)["locationConstraint"])
        assert sent["isRequired"] is True
        rooms = cast("list[Row]", sent["locations"])
        assert rooms[0]["locationEmailAddress"] == _ROOM
        assert rooms[1].get("locationEmailAddress") is None
        (suggestion,) = _list(seen, "suggestions")
        assert _list(suggestion, "locations") == [
            {"display_name": "Room Pilatus", "address": _ROOM}
        ]


_LINKS = [
    pytest.param("outlook_cancel_event", {}, "NOTHING WAS CANCELLED", id="cancel"),
    pytest.param("outlook_delete_event", {}, "The event was not deleted", id="delete"),
    pytest.param(
        "outlook_forward_event",
        {"to": ["priya@example.test"]},
        "This tool forwarded nothing",
        id="forward",
    ),
    pytest.param(
        "outlook_respond_to_invite", {"response": "accept"}, "NO RESPONSE WAS SENT", id="answer"
    ),
    pytest.param("outlook_update_event", {"subject": "Moved"}, "NOTHING WAS CHANGED", id="change"),
]


class TestALinkThatIsNotAMeetingLink:
    @pytest.mark.parametrize(("tool", "arguments", "told"), _LINKS)
    async def test_it_changes_nothing_and_asks_nothing(
        self, graph: respx.MockRouter, tool: str, arguments: Row, told: str
    ) -> None:
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, person=mia, uri="Launch review", **arguments)

        assert told in str(refused.value)
        assert (mia.asked, graph.calls.call_count) == ([], 0)


class TestAForwardThatCannotBeRead:
    @pytest.mark.parametrize(
        ("to", "told"),
        [
            pytest.param(["Priya Rao"], "is not one email address", id="a-name-for-an-address"),
            pytest.param(
                ["priya@example.test", "PRIYA@example.test"], "twice in `to`", id="one-person-twice"
            ),
        ],
    )
    async def test_it_forwards_nothing_and_asks_nothing(
        self, graph: respx.MockRouter, to: list[str], told: str
    ) -> None:
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call("outlook_forward_event", person=mia, uri=_uri(_LAUNCH), to=to)

        assert told in str(refused.value)
        assert "forwarded nothing" in str(refused.value)
        assert (mia.asked, graph.calls.call_count) == ([], 0)

    async def test_a_meeting_with_no_recorded_start_is_named_in_the_question_without_a_time(
        self, graph: respx.MockRouter
    ) -> None:
        _stored(graph, _event(_LAUNCH, "Launch review", organizer=_ANNA) | {"start": None})
        mia = Person(approval="no")

        with pytest.raises(ToolError):
            _ = await _call(
                "outlook_forward_event", person=mia, uri=_uri(_LAUNCH), to=["priya@example.test"]
            )

        assert "at a time that Microsoft did not record" in mia.asked[0]


class TestACancelWhoseAttendeeHasNoAddress:
    async def test_the_attendee_is_named_as_an_attendee_in_the_question(
        self, graph: respx.MockRouter
    ) -> None:
        nameless = _event(_LAUNCH, "Launch review", attendees=[_ANNA])
        nameless["attendees"] = [{"type": "required", "status": {"response": "none"}}]
        _stored(graph, nameless)
        mia = Person(approval="no")

        with pytest.raises(ToolError):
            _ = await _call("outlook_cancel_event", person=mia, uri=_uri(_LAUNCH))

        assert "an attendee" in mia.asked[0]


_PROPOSAL = {"starts_at": "2026-11-09T10:00", "ends_at": "2026-11-09T10:30", "time_zone": _ZURICH}


class TestAnAnswerWithANewTimeThatCannotBeSent:
    @pytest.fixture
    def invitation(self, graph: respx.MockRouter) -> None:
        _stored(graph, _event(_LAUNCH, "Launch review", organizer=_ANNA, attendees=[_MIA]))

    @pytest.mark.usefixtures("invitation")
    @pytest.mark.parametrize(
        ("arguments", "told"),
        [
            pytest.param(
                {"send_response": False, "proposed_new_time": _PROPOSAL},
                "needs `send_response` true",
                id="no-answer-to-carry-it",
            ),
            pytest.param(
                {"proposed_new_time": _PROPOSAL | {"starts_at": "Friday"}},
                "is not a local wall-clock time",
                id="words-for-the-time",
            ),
            pytest.param(
                {"proposed_new_time": _PROPOSAL | {"starts_at": "2026-11-09T11:00"}},
                "is not after its `starts_at`",
                id="ends-before-it-starts",
            ),
        ],
    )
    async def test_it_sends_nothing_and_asks_nothing(self, arguments: Row, told: str) -> None:
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call(
                "outlook_respond_to_invite",
                person=mia,
                uri=_uri(_LAUNCH),
                response="decline",
                **arguments,
            )

        assert told in str(refused.value)
        assert "NO RESPONSE WAS SENT" in str(refused.value)
        assert mia.asked == []


_UPDATES_THAT_CANNOT_BE_READ = [
    pytest.param({}, "given no argument that changes anything", id="nothing-to-change"),
    pytest.param({"location": "   "}, "only whitespace", id="a-blank-place"),
    pytest.param({"starts_at": "2026-11-02T14:00"}, "without the other two", id="half-a-time"),
    pytest.param(
        {"attendees": ["anna@example.test"]}, "without the other", id="half-the-attendees"
    ),
    pytest.param(
        {"add_categories": ["Blue"], "remove_categories": ["blue"]},
        "in both `add_categories` and `remove_categories`",
        id="a-category-in-both-lists",
    ),
    pytest.param(
        {"body_html": "<p>Hello</p>", "online_meeting": True},
        "`body_html` and `online_meeting` together",
        id="a-body-and-a-teams-meeting",
    ),
    pytest.param(
        _MONDAY | {"time_zone": _ZURICH, "starts_at": "Monday"},
        "is not a local wall-clock time",
        id="words-for-the-time",
    ),
    pytest.param(
        _MONDAY | {"time_zone": _ZURICH, "ends_at": "2026-11-02T13:00"},
        "is not after `starts_at`",
        id="ends-before-it-starts",
    ),
    pytest.param(
        {"attendees": ["Anna Meier"], "optional_attendees": []},
        "is not one email address",
        id="a-name-for-an-address",
    ),
    pytest.param(
        {"attendees": ["anna@example.test", "ANNA@example.test"], "optional_attendees": []},
        "twice in `attendees`",
        id="one-person-twice",
    ),
    pytest.param(
        {"attendees": ["anna@example.test"], "optional_attendees": ["anna@example.test"]},
        "in both `attendees` and `optional_attendees`",
        id="one-person-in-both-lists",
    ),
]


class TestAChangeThatCannotBeRead:
    @pytest.mark.parametrize(("arguments", "told"), _UPDATES_THAT_CANNOT_BE_READ)
    async def test_it_changes_nothing_and_asks_nothing_and_says_what_to_correct(
        self, graph: respx.MockRouter, arguments: Row, told: str
    ) -> None:
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call("outlook_update_event", person=mia, uri=_uri(_LAUNCH), **arguments)

        assert told in str(refused.value)
        assert "NOTHING WAS CHANGED" in str(refused.value)
        assert (mia.asked, graph.calls.call_count) == ([], 0)


class TestAChangeThatTheStoredMeetingRefuses:
    @pytest.mark.parametrize(
        ("stored", "arguments", "told"),
        [
            pytest.param(
                _ONLINE, {"online_meeting": True}, "already is an online meeting", id="teams-twice"
            ),
            pytest.param(
                _ONLINE,
                {"body_html": "<p>Other text</p>"},
                "The stored HTML body of this event follows",
                id="a-body-that-drops-the-joining-text",
            ),
            pytest.param(
                _ONLINE
                | {"body": {"contentType": "html", "content": f"<body>{'x' * 16001}</body>"}},
                {"body_html": "<p>Other text</p>"},
                "too long to quote",
                id="a-stored-body-too-long-to-show",
            ),
            pytest.param(
                {"categories": ["Blue"]},
                {"add_categories": ["blue"]},
                "already match `add_categories` and `remove_categories`",
                id="categories-that-are-there",
            ),
            pytest.param(
                {}, {"remove_categories": ["Blue"]}, "The event has no category", id="no-category"
            ),
        ],
    )
    async def test_it_changes_nothing_and_asks_nothing_and_says_why(
        self, graph: respx.MockRouter, stored: Row, arguments: Row, told: str
    ) -> None:
        _stored(graph, {**_event(_LAUNCH, "Launch review", attendees=[_ANNA]), **stored})
        patched = graph.patch(_path(_LAUNCH)).mock(return_value=httpx.Response(200, json={}))
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call("outlook_update_event", person=mia, uri=_uri(_LAUNCH), **arguments)

        assert told in str(refused.value)
        assert (patched.called, mia.asked) == (False, [])

    async def test_a_calendar_that_takes_no_teams_meeting_gets_none(
        self, graph: respx.MockRouter
    ) -> None:
        _stored(graph, _event(_LAUNCH, "Launch review", attendees=[_ANNA]))
        _ = graph.get(f"/me/calendars/{_CALENDAR_ID}").mock(
            return_value=httpx.Response(200, json=_calendar() | _TAKES_NO_TEAMS)
        )
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call(
                "outlook_update_event", person=mia, uri=_uri(_LAUNCH), online_meeting=True
            )

        assert "NOTHING WAS CHANGED" in str(refused.value)
        assert "unknown" in str(refused.value)
        assert mia.asked == []

    async def test_a_body_that_keeps_the_stored_body_is_sent_after_the_question(
        self, graph: respx.MockRouter
    ) -> None:
        _stored(graph, _event(_LAUNCH, "Launch review", attendees=[_ANNA]) | _ONLINE)
        patched = graph.patch(_path(_LAUNCH)).mock(
            return_value=httpx.Response(200, json=_event(_LAUNCH, "Launch review"))
        )
        mia = Person()

        _ = await _call(
            "outlook_update_event",
            person=mia,
            uri=_uri(_LAUNCH),
            body_html="<p>Join   the meeting</p><p>Bring a laptop</p>",
        )

        assert len(mia.asked) == 1
        assert "Bring a laptop" in str(_posted(patched)["body"])


class TestWhatMiaIsToldBeforeAChange:
    @pytest.mark.parametrize(
        ("stored", "arguments", "told"),
        [
            pytest.param(
                {"categories": ["Blue"]},
                {"remove_categories": ["Blue"]},
                "remove every category",
                id="no-category-left",
            ),
            pytest.param(
                {}, {"add_categories": ["Red", "Blue"]}, "set the categories to", id="categories"
            ),
            pytest.param(
                {},
                {"attendees": [], "optional_attendees": []},
                "change the attendee list to nobody",
                id="nobody-left",
            ),
            pytest.param(
                {},
                {"attendees": ["anna@example.test"], "optional_attendees": ["tom@example.test"]},
                "tom@example.test (optional)",
                id="an-optional-attendee",
            ),
        ],
    )
    async def test_the_question_names_the_change(
        self, graph: respx.MockRouter, stored: Row, arguments: Row, told: str
    ) -> None:
        _stored(graph, {**_event(_LAUNCH, "Launch review", attendees=[_ANNA]), **stored})
        mia = Person(approval="no")

        with pytest.raises(ToolError):
            _ = await _call("outlook_update_event", person=mia, uri=_uri(_LAUNCH), **arguments)

        assert told in mia.asked[0]

    async def test_a_place_is_asked_about_also_when_nobody_is_invited(
        self, graph: respx.MockRouter
    ) -> None:
        _stored(graph, _event(_LAUNCH, "Launch review"))
        mia = Person(approval="no")

        with pytest.raises(ToolError):
            _ = await _call(
                "outlook_update_event", person=mia, uri=_uri(_LAUNCH), location="Room Pilatus"
            )

        assert "change the location to 'Room Pilatus'" in mia.asked[0]
