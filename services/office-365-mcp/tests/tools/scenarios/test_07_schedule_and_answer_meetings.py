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
    answer: str | None = None,
    allow_new_time: bool = True,
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
            "response": "organizer" if mine else answer or "notResponded",
            "time": "0001-01-01T00:00:00Z",
        },
        "attendees": [_attendee(one) for one in attendees],
        "allowNewTimeProposals": allow_new_time,
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
    @pytest.fixture(autouse=True)
    def invitation(self, graph: respx.MockRouter) -> None:
        _stored(graph, _event(_LAUNCH, "Launch review", organizer=_ANNA, attendees=[_MIA]))

    async def test_a_decline_carries_the_note_to_the_organizer(
        self, graph: respx.MockRouter
    ) -> None:
        decline = graph.post(f"{_path(_LAUNCH)}/decline").mock(return_value=httpx.Response(202))
        mia = Person()

        seen = await call(
            "outlook_respond_to_invite",
            person=mia,
            uri=_uri(_LAUNCH),
            response="decline",
            comment="I am on leave",
        )

        assert "I am on leave" in mia.asked[0]
        assert _posted(decline)["Comment"] == "I am on leave"
        assert seen["response"] == "declined"

    async def test_a_new_time_is_proposed_when_the_organizer_allows_it(
        self, graph: respx.MockRouter
    ) -> None:
        decline = graph.post(f"{_path(_LAUNCH)}/decline").mock(return_value=httpx.Response(202))
        mia = Person()

        seen = await call(
            "outlook_respond_to_invite",
            person=mia,
            uri=_uri(_LAUNCH),
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
        _stored(graph, _event(_LAUNCH, "Launch review", organizer=_ANNA, allow_new_time=False))
        decline = graph.post(f"{_path(_LAUNCH)}/decline").mock(return_value=httpx.Response(202))
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_respond_to_invite",
                person=mia,
                uri=_uri(_LAUNCH),
                response="decline",
                proposed_new_time={
                    "starts_at": "2026-11-09T10:00",
                    "ends_at": "2026-11-09T10:30",
                    "time_zone": _ZURICH,
                },
            )

        assert "does not allow new time proposals" in str(refused.value)
        assert "remove `proposed_new_time`" in str(refused.value)
        assert (decline.called, mia.asked) == (False, [])

    async def test_a_new_time_is_not_proposed_with_an_acceptance(
        self, graph: respx.MockRouter
    ) -> None:
        accept = graph.post(f"{_path(_LAUNCH)}/accept").mock(return_value=httpx.Response(202))

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_respond_to_invite",
                uri=_uri(_LAUNCH),
                response="accept",
                proposed_new_time={
                    "starts_at": "2026-11-09T10:00",
                    "ends_at": "2026-11-09T10:30",
                    "time_zone": _ZURICH,
                },
            )

        assert "use `decline` or `tentative`" in str(refused.value)
        assert accept.called is False

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
        _ = graph.get("/me/calendar").mock(return_value=httpx.Response(200, json=_calendar()))
        _ = graph.get(f"/me/calendars/{_CALENDAR_ID}/calendarView").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _event(_LAUNCH, "Launch review", organizer=_ANNA),
                        _event(_BUDGET, "Budget review", organizer=_TOM),
                        _event(_SYNC, "Team sync", organizer=_ANNA, answer="accepted"),
                    ]
                },
            )
        )

        seen = await call(
            "outlook_list_events",
            starts_on="2026-11-02",
            ends_on="2026-11-29",
            owner_response="notResponded",
        )

        assert [one["subject"] for one in _list(seen, "events")] == [
            "Launch review",
            "Budget review",
        ]


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
        _ = graph.post("/me/findMeetingTimes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "emptySuggestionsReason": "AttendeesUnavailable",
                    "meetingTimeSuggestions": [],
                },
            )
        )

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
        routes = serve(graph, "rec-tool-outlook_check_availability-tomorrow")
        hours = {
            "daysOfWeek": ["monday", "tuesday"],
            "startTime": "08:00:00.0000000",
            "endTime": "17:00:00.0000000",
            "timeZone": {"name": _ZURICH},
        }
        _ = routes[("POST", "/me/calendar/getSchedule")].mock(
            return_value=httpx.Response(
                200,
                json={"value": [_schedule("anna@example.test", "0" * 20, workingHours=hours)]},
            )
        )

        seen = await _free_times(starts_at="2026-11-03T13:00", ends_at="2026-11-03T15:00")

        (anna,) = _list(seen, "schedules")
        assert anna["availability_view"] == "0" * 20
        assert anna["items"] == []
        hours = _part(anna, "working_hours")
        assert (hours["days"], str(hours["starts_at"])[:5], str(hours["ends_at"])[:5]) == (
            ["monday", "tuesday"],
            "08:00",
            "17:00",
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
        _ = graph.get("/me/outlook/supportedTimeZones()").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "alias": "India Standard Time",
                            "displayName": "(UTC+05:30) Chennai, Kolkata, Mumbai, New Delhi",
                        }
                    ]
                },
            )
        )

        zones = await call("outlook_list_time_zones")
        (mumbai,) = [
            one for one in _list(zones, "time_zones") if "Mumbai" in str(one["display_name"])
        ]
        _ = await _book(
            Person(),
            attendees=["priya@example.test"],
            time_zone=str(mumbai["alias"]),
            starts_at="2026-11-02T15:00",
            ends_at="2026-11-02T15:30",
        )

        assert _part(_posted(routes[("POST", "/me/events")]), "start") == {
            "dateTime": "2026-11-02T15:00",
            "timeZone": "India Standard Time",
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
    @pytest.fixture(autouse=True)
    def meetings(self, graph: respx.MockRouter) -> None:
        _stored_changeable(graph)

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
                ("PATCH", _LAUNCH),
                "outlook_respond_to_invite can accept, decline",
                id="move",
            ),
            pytest.param(
                "outlook_cancel_event",
                {},
                ("POST", f"{_LAUNCH}/cancel"),
                "only the organizer can cancel it",
                id="cancel",
            ),
            pytest.param(
                "outlook_delete_event",
                {},
                ("DELETE", _LAUNCH),
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
        changed = graph.route(method=write[0], path=_path(write[1])).mock(
            return_value=httpx.Response(202)
        )
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, person=mia, uri=_uri(_LAUNCH), **arguments)

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
        removed = graph.delete(_path(_DESIGN)).mock(return_value=httpx.Response(204))
        mia = Person()

        seen = await call("outlook_delete_event", person=mia, uri=_uri(_DESIGN))

        assert "Design review" in mia.asked[0]
        assert "anna@example.test" in mia.asked[0]
        assert removed.called
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
    @pytest.fixture
    def invitation(self, graph: respx.MockRouter) -> None:
        _stored(graph, _event(_LAUNCH, "Launch review", organizer=_ANNA, attendees=[_MIA]))

    @pytest.mark.usefixtures("invitation")
    async def test_an_invitation_is_forwarded_with_the_note_and_the_organizer_is_told(
        self, graph: respx.MockRouter
    ) -> None:
        forward = graph.post(f"{_path(_LAUNCH)}/forward").mock(return_value=httpx.Response(202))
        mia = Person()

        seen = await call(
            "outlook_forward_event",
            person=mia,
            uri=_uri(_LAUNCH),
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
