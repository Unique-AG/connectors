import json
from collections.abc import Awaitable, Callable, Mapping
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
from tests.tools.conftest import GRAPH_V1

from .support import Person, call, response, serve

type Row = Mapping[str, object]

_ZURICH = "Europe/Zurich"
_MIA: Row = {"name": "Mia Keller", "address": "mia@example.test"}
_LENA: Row = {"name": "Lena Frei", "address": "lena@example.test"}
_ANNA: Row = {"name": "Anna Meier", "address": "anna@example.test"}
_LENA_CALENDAR = "AAMkSYNTHETIC-calendar-lena"
_LENA_URI = f"outlook:///calendars/{_LENA_CALENDAR}"
_MIA_CALENDAR = "AAMkSYNTHETIC-calendar-mia"
_ANNA_SHARE = "perm-anna"
_TOM_SHARE = "perm-tom"
_TEAM = "00000000-d034-4a82-8630-01e372765b48"
_TEAM_VIEW = f"/groups/{_TEAM}/calendarView"
_BOOKING: Row = {
    "calendar_ref": _LENA_URI,
    "subject": "Budget review",
    "starts_at": "2026-11-02T14:00",
    "ends_at": "2026-11-02T14:30",
    "time_zone": _ZURICH,
    "attendees": ["anna@example.test"],
}
_TOO_MANY: Json = {
    "status": 429,
    "headers": {"Retry-After": "30"},
    "body": "error.TooManyRequests.json",
}
_REJECTION = {"error": {"code": "ErrorInvalidRequest", "message": "The role is not allowed."}}

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


def _endless() -> Fault:
    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}{_TEAM_VIEW}?$skiptoken=again"}
        )

    return answer


def _calendar(
    calendar_id: str,
    owner: Row,
    *,
    can_edit: bool = True,
    can_share: bool = True,
    default: bool = False,
    removable: bool | None = None,
) -> dict[str, object]:
    return {
        "id": calendar_id,
        "name": str(owner["name"]) if not default else "Calendar",
        "owner": dict(owner),
        "canEdit": can_edit,
        "canShare": can_share,
        "canViewPrivateItems": can_edit,
        "isDefaultCalendar": default,
        "isTallyingResponses": True,
        "isRemovable": removable,
        "allowedOnlineMeetingProviders": ["teamsForBusiness"],
        "defaultOnlineMeetingProvider": "teamsForBusiness",
    }


def _delegated(graph: respx.MockRouter, **calendar: object) -> respx.Route:
    shown = _calendar(_LENA_CALENDAR, _LENA) | calendar
    _ = graph.get(f"/me/calendars/{_LENA_CALENDAR}").mock(
        return_value=httpx.Response(200, json=shown)
    )
    created = {
        "id": "AAMkSYNTHETIC-event-1",
        "subject": "Budget review",
        "start": {"dateTime": "2026-11-02T14:00:00.0000000", "timeZone": _ZURICH},
        "end": {"dateTime": "2026-11-02T14:30:00.0000000", "timeZone": _ZURICH},
        "organizer": {"emailAddress": dict(_LENA)},
        "attendees": [{"emailAddress": dict(_ANNA), "type": "required"}],
    }
    return graph.post(f"/me/calendars/{_LENA_CALENDAR}/events").mock(
        return_value=httpx.Response(201, json=created)
    )


def _permission(
    permission_id: str, who: Row, role: str = "read", *, removable: bool = True
) -> dict[str, object]:
    return {
        "id": permission_id,
        "emailAddress": dict(who),
        "role": role,
        "allowedRoles": ["freeBusyRead", "limitedRead", "read", "write"],
        "isInsideOrganization": True,
        "isRemovable": removable,
    }


def _shareable(graph: respx.MockRouter, *, can_share: bool = True) -> respx.Route:
    calendar = _calendar(_MIA_CALENDAR, _MIA, can_share=can_share)
    _ = graph.get(f"/me/calendars/{_MIA_CALENDAR}").mock(
        return_value=httpx.Response(200, json=calendar)
    )
    return graph.post(f"/me/calendars/{_MIA_CALENDAR}/calendarPermissions").mock(
        return_value=httpx.Response(201, json=_permission(_ANNA_SHARE, _ANNA))
    )


def _shared_with_two(graph: respx.MockRouter) -> list[respx.Route]:
    calendar = _calendar(_MIA_CALENDAR, _MIA)
    _ = graph.get(f"/me/calendars/{_MIA_CALENDAR}").mock(
        return_value=httpx.Response(200, json=calendar)
    )
    shares = (
        (_ANNA_SHARE, _ANNA),
        (_TOM_SHARE, {"name": "Tom Weber", "address": "tom@example.test"}),
    )
    for permission_id, who in shares:
        _ = graph.get(f"/me/calendars/{_MIA_CALENDAR}/calendarPermissions/{permission_id}").mock(
            return_value=httpx.Response(200, json=_permission(permission_id, who))
        )
    return [
        graph.delete(f"/me/calendars/{_MIA_CALENDAR}/calendarPermissions/{permission_id}").mock(
            return_value=httpx.Response(204)
        )
        for permission_id, _who in shares
    ]


def _share_uri(permission_id: str) -> str:
    return f"outlook:///calendarpermissions/{_MIA_CALENDAR}/{permission_id}"


def _recorded(body: str) -> dict[str, object]:
    return cast("dict[str, object]", json.loads((E2E / "bodies" / f"{body}.json").read_text()))


def _posted(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _list(seen: Row, key: str) -> list[Row]:
    return cast("list[Row]", seen[key])


def _part(parent: Row, key: str) -> Row:
    return cast("Row", parent[key])


def _team_event(subject: str, start: str, end: str) -> dict[str, object]:
    return {
        "subject": subject,
        "bodyPreview": f"About {subject}.",
        "start": {"dateTime": f"{start}.0000000", "timeZone": "UTC"},
        "end": {"dateTime": f"{end}.0000000", "timeZone": "UTC"},
        "isAllDay": False,
        "isCancelled": False,
        "type": "singleInstance",
        "organizer": {"emailAddress": dict(_ANNA)},
        "location": {"displayName": ""},
        "webLink": "https://outlook.office365.com/owa/?itemid=synthetic",
    }


async def _platform_week(**arguments: object) -> Row:
    return await _call(
        "outlook_list_group_events",
        **(
            {
                "group_id": _TEAM,
                "starts_on": "2026-11-02",
                "ends_on": "2026-11-08",
                "time_zone": _ZURICH,
            }
            | arguments
        ),
    )


class TestSharingOneOfMiasCalendars:
    async def test_a_colleague_is_given_read_access_after_mia_approves_and_then_shows_in_the_list(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_share_calendar-anna")
        calendars = await call("outlook_list_calendars")
        shared = next(one for one in _list(calendars, "calendars") if "Shared" in str(one["name"]))
        granted = _recorded("rec-tool-outlook_share_calendar-anna.07") | {"role": "read"}
        post = next(route for (method, _path), route in routes.items() if method == "POST")
        _ = post.mock(return_value=httpx.Response(201, json=granted))
        _ = graph.get(
            f"/me/calendars/{unquote(str(shared['uri']).rsplit('/', 1)[1])}/calendarPermissions"
        ).mock(return_value=httpx.Response(200, json={"value": [granted]}))
        mia = Person()

        await call(
            "outlook_share_calendar",
            person=mia,
            calendar_ref=shared["uri"],
            address="anna@example.test",
            role="read",
        )
        listed = await call("outlook_list_calendar_shares", calendar_ref=shared["uri"])

        assert "anna@example.test" in mia.asked[0]
        assert "role read" in mia.asked[0]
        assert _posted(post)["role"] == "read"
        assert [(one["address"], one["role"]) for one in _list(listed, "shares")] == [
            ("anna@example.test", "read")
        ]

    async def test_a_share_is_stopped_after_mia_approves(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-outlook_unshare_calendar-anna")
        calendars = await call("outlook_list_calendars")
        shared = next(one for one in _list(calendars, "calendars") if "Shared" in str(one["name"]))
        granted = await call(
            "outlook_share_calendar",
            person=Person(),
            calendar_ref=shared["uri"],
            address="anna@example.test",
            role="freeBusyRead",
        )
        mia = Person()

        stopped = await call("outlook_unshare_calendar", person=mia, share_ref=granted["uri"])

        assert "anna@example.test" in mia.asked[0]
        assert routes[next(key for key in routes if key[0] == "DELETE")].called
        assert (stopped["address"], stopped["removed"]) == ("anna@example.test", True)

    async def test_a_calendar_that_mia_did_not_create_is_not_shared(
        self, graph: respx.MockRouter
    ) -> None:
        post = _shareable(graph, can_share=False)
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_share_calendar",
                person=mia,
                calendar_ref=f"outlook:///calendars/{_MIA_CALENDAR}",
                address="anna@example.test",
                role="read",
            )

        assert "Only the person who created a calendar can share it" in str(refused.value)
        assert (post.called, mia.asked) == (False, [])

    async def test_the_share_with_the_whole_company_cannot_be_stopped(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_calendar_shares-default")
        (row,) = _list(_recorded("rec-tool-outlook_list_calendar_shares-default.03"), "value")
        listing = await call(
            "outlook_list_events", starts_on="2026-10-30", ends_on="2026-10-30", limit=1
        )
        shares = await call(
            "outlook_list_calendar_shares", calendar_ref=_part(listing, "calendar")["uri"]
        )
        (whole_company,) = _list(shares, "shares")
        calendar_id, permission_id = (
            unquote(one) for one in str(whole_company["uri"]).split("/")[-2:]
        )
        row_path = f"/me/calendars/{calendar_id}/calendarPermissions/{permission_id}"
        _ = graph.get(row_path).mock(return_value=httpx.Response(200, json=row))
        removal = graph.delete(row_path).mock(return_value=httpx.Response(204))
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_unshare_calendar", person=mia, share_ref=whole_company["uri"])

        assert whole_company["is_removable"] is False
        assert "marks this share as not removable" in str(refused.value)
        assert "`My Organization` row" in str(refused.value)
        assert (removal.called, mia.asked) == (False, [])

    async def test_a_role_that_microsoft_refuses_is_reported_after_the_approval_and_shares_nothing(
        self, graph: respx.MockRouter
    ) -> None:
        _ = _shareable(graph)
        _ = graph.post(f"/me/calendars/{_MIA_CALENDAR}/calendarPermissions").mock(
            return_value=httpx.Response(400, json=_REJECTION)
        )
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_share_calendar",
                person=mia,
                calendar_ref=f"outlook:///calendars/{_MIA_CALENDAR}",
                address="anna@example.test",
                role="write",
            )

        assert len(mia.asked) == 1
        assert 'gave this reason: "The role is not allowed."' in str(refused.value)
        assert "will fail the same way" in str(refused.value)


async def _shared_calendar(graph: respx.MockRouter) -> tuple[respx.Route, dict[str, object]]:
    routes = serve(graph, "rec-tool-outlook_create_event_on_behalf-shared-calendar")
    calendars = await call("outlook_list_calendars")
    shared = next(one for one in _list(calendars, "calendars") if "Shared" in str(one["name"]))
    (create,) = [route for (method, _path), route in routes.items() if method == "POST"]
    return create, dict(_BOOKING) | {"calendar_ref": shared["uri"]}


class TestActingOnTheCalendarOfAManager:
    async def test_a_meeting_is_booked_on_the_calendar_of_the_manager_after_mia_approves(
        self, graph: respx.MockRouter
    ) -> None:
        create = _delegated(graph)
        mia = Person()

        seen = await _call("outlook_create_event_on_behalf", person=mia, **_BOOKING)

        assert "anna@example.test" in mia.asked[0]
        assert [one["emailAddress"] for one in cast("list[Row]", _posted(create)["attendees"])] == [
            {"address": "anna@example.test"}
        ]
        assert _part(seen, "organizer")["name"] == "Lena Frei"

    async def test_a_calendar_that_was_shared_for_reading_only_is_not_written_to(
        self, graph: respx.MockRouter
    ) -> None:
        create = _delegated(graph, canEdit=False)
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call("outlook_create_event_on_behalf", person=mia, **_BOOKING)

        assert "can read that calendar and cannot add to it" in str(refused.value)
        assert "owner has to grant them edit access in Outlook first" in str(refused.value)
        assert (create.called, mia.asked) == (False, [])

    async def test_a_calendar_that_nobody_shared_is_not_listed_and_gets_no_event(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_calendars-all")
        calendars = await call("outlook_list_calendars")
        _ = graph.get(f"/me/calendars/{_LENA_CALENDAR}").mock(
            return_value=response({"status": 404, "body": "error.itemNotFound.json"})
        )
        create = graph.post(f"/me/calendars/{_LENA_CALENDAR}/events")
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await _call("outlook_create_event_on_behalf", person=mia, **_BOOKING)

        assert not [one for one in _list(calendars, "calendars") if _LENA_CALENDAR in str(one)]
        assert "the calendar is no longer theirs to write to" in str(refused.value)
        assert (create.called, mia.asked) == (False, [])

    @pytest.mark.parametrize(
        ("answer", "told"),
        [
            *_REFUSALS,
            pytest.param(
                {"status": 404, "body": "error.itemNotFound.json"},
                "the calendar is no longer theirs to write to",
                id="no-calendar-any-more",
            ),
            pytest.param(
                None, 'gave this reason: "The role is not allowed."', id="rejected-booking"
            ),
        ],
    )
    async def test_a_booking_that_microsoft_refuses_is_explained_and_creates_nothing(
        self, graph: respx.MockRouter, answer: Json | None, told: str
    ) -> None:
        create, booking = await _shared_calendar(graph)
        _ = create.mock(side_effect=_rejection() if answer is None else _reply(answer))

        with pytest.raises(ToolError) as refused:
            _ = await _call("outlook_create_event_on_behalf", **booking)

        assert told in str(refused.value)
        assert create.call_count == 1

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(_reply({"status": 504}), id="fails"),
            pytest.param(httpx.ReadTimeout, id="no-answer-in-time"),
        ],
    )
    async def test_a_booking_that_microsoft_fails_is_not_repeated_and_the_calendar_is_read_first(
        self, graph: respx.MockRouter, failure: Fault
    ) -> None:
        create, booking = await _shared_calendar(graph)
        _ = create.mock(side_effect=failure)

        with pytest.raises(ToolError) as refused:
            _ = await _call("outlook_create_event_on_behalf", **booking)

        assert "does not know if Microsoft 365 made the change" in str(refused.value)
        assert "Do not call this tool again first" in str(refused.value)
        assert "outlook_list_events" in str(refused.value)
        assert create.call_count == 1


class TestATeamCalendar:
    async def test_it_lists_the_four_events_of_the_calendar_of_a_team(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_group_events-team")
        week = [
            _team_event(f"Platform event {n}", f"2026-11-0{n}T08:00:00", f"2026-11-0{n}T09:00:00")
            for n in range(2, 6)
        ]
        _ = routes[("GET", _TEAM_VIEW)].mock(return_value=httpx.Response(200, json={"value": week}))

        (platform,) = _list(await call("teams_list_my_teams"), "teams")
        seen = await _platform_week(group_id=platform["team_id"])

        assert [one["subject"] for one in _list(seen, "events")] == [
            "Platform event 2",
            "Platform event 3",
            "Platform event 4",
            "Platform event 5",
        ]
        assert _part(_list(seen, "events")[0], "start")["iso"] == "2026-11-02T09:00:00+01:00"

    @pytest.mark.parametrize(
        ("answer", "told"),
        [
            *_REFUSALS,
            pytest.param(
                None, 'gave this reason: "The role is not allowed."', id="rejected-question"
            ),
        ],
    )
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_team_calendar_that_microsoft_refuses_is_explained_and_lists_no_event(
        self, graph: respx.MockRouter, answer: Json | None, told: str
    ) -> None:
        _ = graph.get(_TEAM_VIEW).mock(
            side_effect=_rejection() if answer is None else _reply(answer)
        )

        with pytest.raises(ToolError) as refused:
            _ = await _platform_week()

        assert told in str(refused.value)

    async def test_a_team_without_a_calendar_is_reported_with_the_way_to_look_the_teams_up_again(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_TEAM_VIEW).mock(
            return_value=response({"status": 404, "body": "error.itemNotFound.json"})
        )

        with pytest.raises(ToolError) as refused:
            _ = await _platform_week()

        assert "Call teams_list_my_teams again" in str(refused.value)

    @pytest.mark.parametrize(
        ("failure", "told"),
        [
            pytest.param(
                _reply({"status": 500, "body": "error.generalException.json"}),
                "Retry once; if it fails again the same way, stop and report it",
                id="fails",
            ),
            pytest.param(
                httpx.ReadTimeout, "Retry once; if it fails again the same way", id="no-answer"
            ),
            pytest.param(
                _endless(),
                "would not finish sending this list",
                id="endless-list",
            ),
        ],
    )
    async def test_a_team_calendar_that_cannot_be_read_to_the_end_is_not_reported_as_empty(
        self, graph: respx.MockRouter, failure: Fault, told: str
    ) -> None:
        _ = graph.get(_TEAM_VIEW).mock(side_effect=failure)

        with pytest.raises(ToolError) as refused:
            _ = await _platform_week()

        assert told in str(refused.value)
        assert "Retry once" in str(refused.value)

    async def test_one_busy_answer_is_waited_out_inside_the_same_call(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        _ = graph.get(_TEAM_VIEW).mock(
            side_effect=[
                response(_TOO_MANY),
                httpx.Response(
                    200,
                    json={
                        "value": [
                            _team_event(
                                "Platform sync", "2026-11-02T08:00:00", "2026-11-02T09:00:00"
                            )
                        ]
                    },
                ),
            ]
        )

        seen = await _platform_week()

        assert [one["subject"] for one in _list(seen, "events")] == ["Platform sync"]
        assert retry_sleeps.delays == [30]


_SHARE: Row = {
    "calendar_ref": f"outlook:///calendars/{_MIA_CALENDAR}",
    "address": "anna@example.test",
    "role": "read",
}

_APPROVAL_ROWS = [
    pytest.param("outlook_share_calendar", _SHARE, _SHARE | {"role": "write"}, id="share"),
    pytest.param(
        "outlook_unshare_calendar",
        {"share_ref": _share_uri(_ANNA_SHARE)},
        {"share_ref": _share_uri(_TOM_SHARE)},
        id="unshare",
    ),
    pytest.param(
        "outlook_create_event_on_behalf",
        _BOOKING,
        _BOOKING | {"starts_at": "2026-11-02T15:00", "ends_at": "2026-11-02T15:30"},
        id="book-on-the-calendar-of-a-manager",
    ),
]


def _writes(graph: respx.MockRouter) -> list[respx.Route]:
    return [_shareable(graph), *_shared_with_two(graph), _delegated(graph)]


class TestNothingIsDoneWithoutAnApproval:
    @pytest.mark.parametrize(("tool", "arguments", "_other"), _APPROVAL_ROWS)
    async def test_an_approval_that_mia_refuses_changes_nothing_and_says_it_was_not_confirmed(
        self, graph: respx.MockRouter, tool: str, arguments: Row, _other: Row
    ) -> None:
        writes = _writes(graph)
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
        writes = _writes(graph)

        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, person=Person(approval="unanswered"), **arguments)

        assert "received no answer" in str(refused.value)
        assert "make the same request again" in str(refused.value)
        assert [route for route in writes if route.called] == []

    @pytest.mark.parametrize(("tool", "approved", "attempted"), _APPROVAL_ROWS)
    async def test_an_approval_for_one_request_does_not_cover_another(
        self, graph: respx.MockRouter, tool: str, approved: Row, attempted: Row
    ) -> None:
        writes = _writes(graph)
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


class TestDeletingACalendar:
    async def _spare(
        self, graph: respx.MockRouter
    ) -> tuple[Mapping[tuple[str, str], respx.Route], Row]:
        routes = serve(graph, "rec-tool-outlook_delete_calendar-spare")
        calendars = await call("outlook_list_calendars")
        return routes, next(
            one for one in _list(calendars, "calendars") if "Spare" in str(one["name"])
        )

    async def test_an_empty_calendar_of_mia_is_deleted_after_she_approves(
        self, graph: respx.MockRouter
    ) -> None:
        routes, spare = await self._spare(graph)
        mia = Person()

        seen = await call("outlook_delete_calendar", person=mia, calendar_ref=spare["uri"])

        assert "holds no event" in mia.asked[0]
        assert routes[next(key for key in routes if key[0] == "DELETE")].called
        assert seen["deleted"] is True

    @pytest.mark.parametrize(
        ("change", "told"),
        [
            pytest.param(
                {"isDefaultCalendar": True},
                "deletes only a calendar other than the default",
                id="main",
            ),
            pytest.param(
                {"owner": dict(_LENA)},
                "deletes only a calendar that the signed-in user owns",
                id="not-owned",
            ),
            pytest.param(
                {"isRemovable": False}, "marks this calendar as not removable", id="not-removable"
            ),
        ],
    )
    async def test_a_calendar_that_cannot_be_deleted_is_explained_and_stays(
        self, graph: respx.MockRouter, change: Row, told: str
    ) -> None:
        routes, spare = await self._spare(graph)
        calendar_id = unquote(str(spare["uri"]).rsplit("/", 1)[1])
        stored = _recorded("rec-tool-outlook_delete_calendar-spare.03") | dict(change)
        _ = routes[("GET", f"/me/calendars/{calendar_id}")].mock(
            return_value=httpx.Response(200, json=stored)
        )
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_delete_calendar", person=mia, calendar_ref=spare["uri"])

        assert told in str(refused.value)
        assert (routes[next(key for key in routes if key[0] == "DELETE")].called, mia.asked) == (
            False,
            [],
        )

    async def test_a_calendar_that_holds_a_meeting_is_not_deleted(
        self, graph: respx.MockRouter
    ) -> None:
        routes, spare = await self._spare(graph)
        calendar_id = unquote(str(spare["uri"]).rsplit("/", 1)[1])
        _ = routes[("GET", f"/me/calendars/{calendar_id}/events")].mock(
            return_value=httpx.Response(200, json={"value": [{"id": "AAMkSYNTHETIC-event-1"}]})
        )
        mia = Person()

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_delete_calendar", person=mia, calendar_ref=spare["uri"])

        assert "holds at least one event" in str(refused.value)
        assert routes[next(key for key in routes if key[0] == "DELETE")].called is False
