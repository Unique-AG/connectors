import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, tzinfo
from typing import Self, cast, override
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError

from office_365_mcp.shared import meetings
from office_365_mcp.shared.handles import meeting_uri_for
from tests.e2e.test_scenarios import build_server, patch_obo
from tests.graph_fixtures import E2E
from tests.tools.conftest import (
    JOIN_WEB_URL,
    ME,
    MEETING_ID,
    OTHER_USER_ID,
    SIGNED_IN_USER_ID,
    meeting_payload,
)
from tests.tools.scenarios.support import Person, call, serve
from tests.tools.scenarios.teams_support import (
    Says,
    call_on_the_newer_protocol,
    refused_on_the_newer_protocol,
)

type Row = Mapping[str, object]

ANNA = {"user_id": "00000000-a6b4-4b6e-8a2b-9e1c3f1e88e1", "name": "Anna Meier"}
TOM = {"user_id": "00000000-e469-40d3-8f5b-9a7c5dac541e", "name": "Tom Berger"}
PRIYA = {"user_id": "00000000-0000-4000-8000-0000000000a3", "name": "Priya Rao"}
GUEST_UPN = "guest@outside.invalid"

CHAT_ID = "19:launch@thread.v2"
CHAT_PATH = f"/chats/{quote(CHAT_ID, safe='')}"
TOM_MEMBERSHIP = "TOMMEMBERSHIP"
MEETING_URI = cast("str", meeting_uri_for(JOIN_WEB_URL))
MEETING_PATH = f"/me/onlineMeetings/{MEETING_ID}"
TOMORROW_AT_15 = {"starts_at": "2026-03-02T15:00:00Z", "ends_at": "2026-03-02T15:30:00Z"}
NOT_AGREED = "did not agree"
LONG_AGO = "2026-02-10T15:00:00Z"


def _the_clock_reads(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    class Frozen(datetime):
        @override
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls.fromtimestamp(moment.timestamp(), tz)

    monkeypatch.setattr(meetings, "datetime", Frozen)


def _rows(value: object) -> list[Row]:
    return cast("list[Row]", value)


def _uncalled(routes: Mapping[tuple[str, str], respx.Route]) -> list[tuple[str, str]]:
    return [key for key, route in routes.items() if not route.called]


def _error(code: str, message: str) -> Row:
    return {"error": {"code": code, "message": message}}


async def _refused_by(person: Person | None, tool: str, /, **arguments: object) -> str:
    with pytest.raises(ToolError) as raised:
        _ = await call(tool, person=person, **arguments)
    return str(raised.value)


async def _a_new_group_chat(mia: Person) -> Row:
    return await call("teams_create_chat", person=mia, **SEED_CHAT)


async def _called(tool: str, /, **arguments: object) -> Row:
    return await call(tool, person=None, **arguments)


def _the_route(routes: Mapping[tuple[str, str], respx.Route], method: str) -> respx.Route:
    return next(route for (verb, _path), route in routes.items() if verb == method)


def _made(graph: respx.MockRouter) -> list[tuple[str, str]]:
    calls = cast("list[tuple[httpx.Request, object]]", list(graph.calls))
    return [(request.method, request.url.path) for request, _ in calls]


async def _refused(tool: str, /, **arguments: object) -> str:
    return await _refused_by(None, tool, **arguments)


async def _call_from_a_client_that_cannot_ask(tool: str, **arguments: object) -> str:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        async with Client(FastMCPTransport(build_server()), mode="legacy") as client:
            with pytest.raises(ToolError) as raised:
                _ = await client.call_tool(tool, arguments)
    return str(raised.value)


def _body(route: respx.Route) -> Row:
    return cast("Row", json.loads(route.calls.last.request.content))


def _writes(graph: respx.MockRouter) -> respx.Route:
    return graph.route(method__in=["POST", "PATCH", "PUT", "DELETE"]).mock(
        return_value=httpx.Response(204)
    )


def _signed_in(graph: respx.MockRouter) -> None:
    _ = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))


def _the_chat_is_called(graph: respx.MockRouter, topic: str | None = "Launch") -> None:
    _ = graph.get(CHAT_PATH).mock(
        return_value=httpx.Response(200, json={"id": CHAT_ID, "chatType": "group", "topic": topic})
    )


def _tom_is_a_member(graph: respx.MockRouter) -> None:
    _ = graph.get(f"{CHAT_PATH}/members/{TOM_MEMBERSHIP}").mock(
        return_value=httpx.Response(
            200,
            json={
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "id": TOM_MEMBERSHIP,
                "displayName": TOM["name"],
                "userId": TOM["user_id"],
                "email": "tom@example.invalid",
            },
        )
    )


def _meeting(
    *, organizer: str = SIGNED_IN_USER_ID, attendees: Sequence[str | None] = (), end: str = LONG_AGO
) -> Row:
    invitees = [
        {"upn": GUEST_UPN} if one is None else {"identity": {"user": {"id": one}}, "upn": one}
        for one in attendees
    ]
    return {
        **meeting_payload(end=end),
        "participants": {
            "organizer": {"identity": {"user": {"id": organizer}}, "upn": "mia@example.invalid"},
            "attendees": invitees,
        },
    }


def _the_meeting_is(graph: respx.MockRouter, meeting: Row) -> None:
    _ = graph.get("/me/onlineMeetings").mock(
        return_value=httpx.Response(200, json={"value": [dict(meeting)]})
    )
    _signed_in(graph)


def _the_writes_are_answered(graph: respx.MockRouter) -> respx.Route:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(204)
        if "/onlineMeetings" in request.url.path:
            return httpx.Response(200, json=_meeting(attendees=[ANNA["user_id"]]))
        if request.url.path.endswith("/members"):
            return httpx.Response(
                201,
                json={"@odata.type": "#microsoft.graph.aadUserConversationMember", "id": "NEW"},
            )
        return httpx.Response(200, json={"id": CHAT_ID, "chatType": "group", "topic": "Launch"})

    return graph.route(method__in=["POST", "PATCH", "PUT", "DELETE"]).mock(side_effect=answer)


def _everything_is_readable(
    graph: respx.MockRouter, writes: Callable[[respx.MockRouter], respx.Route] = _writes
) -> respx.Route:
    _signed_in(graph)
    _the_chat_is_called(graph)
    _tom_is_a_member(graph)
    _the_meeting_is(graph, _meeting(attendees=[ANNA["user_id"], TOM["user_id"]]))
    return writes(graph)


def _members_of(body: Row) -> list[str]:
    binds = [cast("str", member["user@odata.bind"]) for member in _rows(body["members"])]
    return [cast("re.Match[str]", re.search(r"users\('([^']+)'\)", bind))[1] for bind in binds]


def _recorded_join_url() -> str:
    page = cast(
        "Row",
        json.loads((E2E / "bodies" / "rec-tool-teams_delete_meeting-created.02.json").read_text()),
    )
    return cast("str", _rows(page["value"])[0]["joinWebUrl"])


NEW_CHAT = {"chat_type": "group", "topic": "Launch", "members": [ANNA, TOM]}
SEED_TOPIC = "seed-v1 case-teams-chat"
RENAMED_SEED_TOPIC = f"{SEED_TOPIC} renamed"
SEED_CHAT = {**NEW_CHAT, "topic": SEED_TOPIC}
ADD_PRIYA = {"chat_id": CHAT_ID, "member": PRIYA}
REMOVE_TOM = {"chat_id": CHAT_ID, "membership_id": TOM_MEMBERSHIP}
RENAME = {"chat_id": CHAT_ID, "topic": "Launch 2.0"}
NEW_MEETING = {
    "subject": "Design review",
    "starts_at": "2026-03-02T14:00:00Z",
    "ends_at": "2026-03-02T14:30:00Z",
    "attendees": [ANNA],
}
MOVE_MEETING = {"meeting_uri": MEETING_URI, **TOMORROW_AT_15}
DELETE_MEETING = {"meeting_uri": MEETING_URI}

EVERY_PROPOSAL = [
    pytest.param("teams_create_chat", NEW_CHAT, "No chat was created.", id="create-chat"),
    pytest.param("teams_add_chat_member", ADD_PRIYA, "Nobody was added.", id="add-member"),
    pytest.param("teams_remove_chat_member", REMOVE_TOM, "Nobody was removed.", id="remove-member"),
    pytest.param("teams_rename_chat", RENAME, "Nothing was renamed.", id="rename-chat"),
    pytest.param(
        "teams_create_meeting", NEW_MEETING, "No meeting was created.", id="create-meeting"
    ),
    pytest.param(
        "teams_update_meeting", MOVE_MEETING, "No meeting was changed.", id="update-meeting"
    ),
    pytest.param(
        "teams_delete_meeting", DELETE_MEETING, "No meeting was deleted.", id="delete-meeting"
    ),
]


class TestMiaControlsWhoIsInAGroupChat:
    async def test_it_refuses_a_display_name_because_only_entra_ids_name_a_person(
        self, graph: respx.MockRouter
    ) -> None:
        mia = Person()

        message = await _refused_by(
            mia,
            "teams_create_chat",
            chat_type="group",
            topic="Launch",
            members=[{"user_id": "Anna", "name": "Anna"}],
        )

        assert "user_id" in message and "pattern" in message
        assert mia.asked == [] and not graph.calls

    async def test_it_creates_a_group_chat_from_people_mia_already_chats_with(
        self, graph: respx.MockRouter
    ) -> None:
        routes = {
            **serve(graph, "rec-tool-teams_list_chats-all"),
            **serve(graph, "rec-tool-teams_create_chat-group"),
        }
        chats = _rows((await call("teams_list_chats", chat_type="oneOnOne"))["chats"])
        mia_and_partner = _rows(chats[0]["members"])
        partner = next(one for one in mia_and_partner if one["display_name"] != "Mia Keller")
        mia = Person()

        result = await call(
            "teams_create_chat",
            person=mia,
            **{
                **SEED_CHAT,
                "members": [{"user_id": partner["user_id"], "name": partner["display_name"]}, TOM],
            },
        )

        assert _uncalled(routes) == []
        assert len(mia.asked) == 1 and SEED_TOPIC in mia.asked[0] and TOM["user_id"] in mia.asked[0]
        body = _body(routes[("POST", "/chats")])
        assert (body["chatType"], body["topic"]) == ("group", SEED_TOPIC)
        assert sorted(_members_of(body)) == sorted(
            [cast("str", one["user_id"]) for one in mia_and_partner] + [TOM["user_id"]]
        )
        assert result["topic"] == SEED_TOPIC

    @pytest.mark.parametrize(
        ("share_history", "told"),
        [(True, "will see all earlier messages"), (False, "will not see the earlier messages")],
    )
    async def test_it_tells_mia_in_the_question_whether_the_new_member_sees_the_earlier_messages(
        self, graph: respx.MockRouter, share_history: bool, told: str
    ) -> None:
        routes = serve(graph, "rec-tool-teams_add_chat_member-tom")
        mia = Person()
        chat = await _a_new_group_chat(mia)
        members = _rows((await call("teams_list_chat_members", chat_id=chat["chat_id"]))["members"])
        tom = next(one for one in members if one["display_name"] == "Tom Berger")
        _ = await call(
            "teams_remove_chat_member",
            person=mia,
            chat_id=chat["chat_id"],
            membership_id=tom["membership_id"],
        )

        result = await call(
            "teams_add_chat_member",
            person=mia,
            chat_id=chat["chat_id"],
            member={"user_id": tom["user_id"], "name": tom["display_name"]},
            share_history=share_history,
        )

        assert _uncalled(routes) == []
        assert told in mia.asked[-1] and SEED_TOPIC in mia.asked[-1]
        added = routes[("POST", f"/chats/{chat['chat_id']}/members")]
        assert ("visibleHistoryStartDateTime" in _body(added)) is share_history
        assert result["shared_history"] is share_history

    async def test_it_removes_a_member_after_mia_approves_the_change(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_remove_chat_member-tom")
        mia = Person()
        chat = await _a_new_group_chat(mia)
        members = _rows((await call("teams_list_chat_members", chat_id=chat["chat_id"]))["members"])
        tom = next(one for one in members if one["display_name"] == "Tom Berger")

        removed = await call(
            "teams_remove_chat_member",
            person=mia,
            chat_id=chat["chat_id"],
            membership_id=tom["membership_id"],
        )

        assert _uncalled(routes) == []
        assert "Tom Berger" in mia.asked[-1] and SEED_TOPIC in mia.asked[-1]
        assert removed["membership_id"] == tom["membership_id"]

    async def test_it_reads_the_chat_type_of_a_one_to_one_chat_and_adds_nobody(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-teams_list_chats-all")

        chats = _rows((await call("teams_list_chats", chat_type="oneOnOne"))["chats"])

        assert chats and {chat["chat_type"] for chat in chats} == {"oneOnOne"}
        assert {method for method, _path in _made(graph)} == {"GET"}

    async def test_it_reports_the_reason_when_microsoft_refuses_a_member_for_a_one_to_one_chat(
        self, graph: respx.MockRouter
    ) -> None:
        _the_chat_is_called(graph, topic=None)
        _ = graph.get(f"{CHAT_PATH}/members").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        attempt = graph.post(f"{CHAT_PATH}/members").mock(
            return_value=httpx.Response(
                400, json=_error("BadRequest", "Members cannot be added to a one-on-one chat")
            )
        )

        mia = Person()

        message = await _refused_by(mia, "teams_add_chat_member", **ADD_PRIYA)

        assert 'gave this reason: "Members cannot be added to a one-on-one chat"' in message
        assert len(mia.asked) == 1
        assert attempt.call_count == 1

    async def test_it_renames_a_group_chat_and_changes_nothing_else_about_it(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_rename_chat-group")
        mia = Person()
        chat = await _a_new_group_chat(mia)

        renamed = await call(
            "teams_rename_chat", person=mia, chat_id=chat["chat_id"], topic=RENAMED_SEED_TOPIC
        )

        assert _uncalled(routes) == []
        assert RENAMED_SEED_TOPIC in mia.asked[-1]
        rename = routes[("PATCH", f"/chats/{chat['chat_id']}")]
        assert {key for key in _body(rename) if not key.startswith("@")} == {"topic"}
        assert renamed["topic"] == RENAMED_SEED_TOPIC


class TestAnOnlineMeetingBelongsToItsOrganizer:
    async def test_it_creates_a_meeting_and_gives_mia_the_join_address(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_create_meeting-solo")
        recorded = cast(
            "Row",
            json.loads((E2E / "bodies" / "rec-tool-teams_create_meeting-solo.01.json").read_text()),
        )
        mia = Person()

        created = await call("teams_create_meeting", person=mia, **NEW_MEETING)

        sent = _body(routes[("POST", "/me/onlineMeetings/createOrGet")])
        assert (sent["subject"], sent["startDateTime"], sent["endDateTime"]) == (
            "Design review",
            "2026-03-02T14:00:00+00:00",
            "2026-03-02T14:30:00+00:00",
        )
        assert created["join_web_url"] == recorded["joinWebUrl"]
        assert created["meeting_uri"] == meeting_uri_for(cast("str", recorded["joinWebUrl"]))
        assert "no calendar" in mia.asked[0]
        assert _made(graph) == [("POST", "/v1.0/me/onlineMeetings/createOrGet")]

    async def test_it_sends_the_attendees_with_the_meeting_and_gives_them_back(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_create_meeting-attendees")
        attendees = [ANNA["user_id"], TOM["user_id"]]

        created = await _called("teams_create_meeting", **{**NEW_MEETING, "attendees": [ANNA, TOM]})

        sent = [
            cast("str", cast("Row", cast("Row", one["identity"])["user"])["id"])
            for one in _rows(
                cast(
                    "Row", _body(routes[("POST", "/me/onlineMeetings/createOrGet")])["participants"]
                )["attendees"]
            )
        ]
        assert sent == attendees
        assert created["attendee_ids"] == attendees

    async def test_it_shows_attendance_only_to_the_organizer(self, graph: respx.MockRouter) -> None:
        _the_meeting_is(graph, _meeting(organizer=OTHER_USER_ID))
        reports = graph.get(f"{MEETING_PATH}/attendanceReports")

        result = await call("teams_read_meeting", meeting_uri=MEETING_URI)

        assert result["status"] == "not_organizer"
        assert result["reports"] == [] and result["newest_report_attendance"] == []
        assert not reports.called

    async def test_it_names_each_attendee_with_the_time_that_person_attended(
        self, graph: respx.MockRouter
    ) -> None:
        _the_meeting_is(graph, _meeting(attendees=[ANNA["user_id"], TOM["user_id"]]))
        _ = graph.get(f"{MEETING_PATH}/attendanceReports").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "report1",
                            "totalParticipantCount": 2,
                            "meetingStartDateTime": "2026-02-10T14:00:00Z",
                            "meetingEndDateTime": "2026-02-10T15:00:00Z",
                        }
                    ]
                },
            )
        )
        records: list[Row] = [
            {
                "emailAddress": f"{name.lower()}@example.invalid",
                "identity": {"displayName": name},
                "role": "Attendee",
                "totalAttendanceInSeconds": seconds,
                "attendanceIntervals": [
                    {
                        "joinDateTime": "2026-02-10T14:00:00Z",
                        "leaveDateTime": "2026-02-10T14:25:00Z",
                        "durationInSeconds": seconds,
                    }
                ],
            }
            for name, seconds in (("Anna", 25 * 60), ("Tom", 40 * 60))
        ]
        _ = graph.get(f"{MEETING_PATH}/attendanceReports/report1/attendanceRecords").mock(
            return_value=httpx.Response(200, json={"value": records})
        )

        result = await call("teams_read_meeting", meeting_uri=MEETING_URI)

        assert result["status"] == "available"
        assert [
            (one["display_name"], one["total_attendance_seconds"])
            for one in _rows(result["newest_report_attendance"])
        ] == [("Anna", 1500), ("Tom", 2400)]
        invitees = _rows(cast("Row", result["meeting"])["attendees"])
        assert [one["user_id"] for one in invitees] == [ANNA["user_id"], TOM["user_id"]]
        (span,) = _rows(_rows(result["newest_report_attendance"])[0]["intervals"])
        assert str(span["joined_at"]).startswith("2026-02-10T14:00")
        assert str(span["left_at"]).startswith("2026-02-10T14:25")

    async def test_it_moves_a_meeting_and_leaves_its_attendees_and_every_calendar_alone(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_update_meeting-move")
        mia = Person()
        created = await call(
            "teams_create_meeting", person=mia, **{**NEW_MEETING, "attendees": [ANNA, TOM]}
        )

        result = await call(
            "teams_update_meeting",
            person=mia,
            meeting_uri=created["meeting_uri"],
            **TOMORROW_AT_15,
        )

        assert "2026-03-02T15:00:00+00:00 until 2026-03-02T15:30:00+00:00" in mia.asked[-1]
        assert _body(_the_route(routes, "PATCH")) == {
            "@odata.type": "#microsoft.graph.onlineMeeting",
            "startDateTime": "2026-03-02T15:00:00+00:00",
            "endDateTime": "2026-03-02T15:30:00+00:00",
        }
        assert result["attendee_ids"] == [ANNA["user_id"], TOM["user_id"]]
        assert str(result["start"]).startswith("2026-11-03T19:00")
        assert all("/events" not in path for _, path in _made(graph))

    async def test_it_adds_an_attendee_and_keeps_the_earlier_attendees(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_update_meeting-add-attendee")
        mia = Person()
        created = await call(
            "teams_create_meeting", person=mia, **{**NEW_MEETING, "attendees": [ANNA]}
        )
        everyone = [ANNA["user_id"], TOM["user_id"]]

        result = await call(
            "teams_update_meeting",
            person=mia,
            meeting_uri=created["meeting_uri"],
            attendees=[ANNA, TOM],
        )

        sent = _rows(cast("Row", _body(_the_route(routes, "PATCH"))["participants"])["attendees"])
        assert [cast("Row", cast("Row", one["identity"])["user"])["id"] for one in sent] == everyone
        assert "removes" not in mia.asked[-1]
        assert result["attendee_ids"] == everyone
        assert all("/events" not in path for _, path in _made(graph))

    async def test_it_names_the_guest_that_a_new_attendee_list_would_remove(
        self, graph: respx.MockRouter
    ) -> None:
        _the_meeting_is(graph, _meeting(attendees=[ANNA["user_id"], None]))
        _ = graph.patch(MEETING_PATH).mock(
            return_value=httpx.Response(200, json=_meeting(attendees=[ANNA["user_id"]]))
        )
        mia = Person()

        _ = await call(
            "teams_update_meeting", person=mia, meeting_uri=MEETING_URI, attendees=[ANNA, PRIYA]
        )

        assert f"The change removes '{GUEST_UPN}'." in mia.asked[0]

    async def test_it_deletes_a_meeting_after_mia_approves_the_deletion(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-teams_delete_meeting-created")
        mia = Person()

        deleted = await call(
            "teams_delete_meeting", person=mia, meeting_uri=meeting_uri_for(_recorded_join_url())
        )

        assert len(mia.asked) == 1 and "Delete the Teams meeting" in mia.asked[0]
        assert deleted["subject"]
        assert [method for method, _ in _made(graph)].count("DELETE") == 1
        assert all("/events" not in path for _, path in _made(graph))


class TestWhenMicrosoftCannotDoWhatMiaAsked:
    async def test_it_tells_mia_to_sign_in_again_and_creates_no_chat(
        self, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        created = graph.post("/chats").mock(
            return_value=httpx.Response(401, json=_error("InvalidAuthenticationToken", "expired"))
        )

        message = await _refused("teams_create_chat", **NEW_CHAT)

        assert "sign in to this connector again" in message
        assert created.call_count == 1

    async def test_it_tells_mia_that_an_administrator_must_grant_the_access_for_the_new_chat(
        self, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        _ = graph.post("/chats").mock(
            return_value=httpx.Response(403, json=_error("Forbidden", "denied"))
        )

        message = await _refused("teams_create_chat", **NEW_CHAT)

        assert "Chat.Create" in message and "administrator" in message

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_it_tells_mia_how_long_to_wait_and_does_not_create_the_chat_again_sooner(
        self, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        created = graph.post("/chats").mock(
            return_value=httpx.Response(
                429, headers={"Retry-After": "30"}, json=_error("TooManyRequests", "slow")
            )
        )

        message = await _refused("teams_create_chat", **NEW_CHAT)

        assert "30 seconds" in message and "not sooner" in message
        assert created.call_count == 1

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.Response(500, json=_error("InternalServerError", "boom")),
            httpx.ReadTimeout("no answer in time"),
            httpx.Response(200, text="<html>x</html>", headers={"content-type": "text/html"}),
        ],
        ids=["internal-error", "timeout", "unreadable-answer"],
    )
    async def test_it_does_not_create_a_failed_chat_again_before_the_chats_are_checked(
        self, graph: respx.MockRouter, failure: httpx.Response | Exception
    ) -> None:
        _signed_in(graph)
        created = graph.post("/chats")
        _ = (
            created.mock(side_effect=failure)
            if isinstance(failure, Exception)
            else created.mock(return_value=failure)
        )

        message = await _refused("teams_create_chat", **NEW_CHAT)

        assert "does not know if Microsoft 365 made the change" in message
        assert "Do not call this tool again first." in message
        assert "use teams_list_chats" in message
        assert created.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_it_makes_no_fifth_addition_within_a_minute_and_tells_mia_to_wait(
        self, graph: respx.MockRouter
    ) -> None:
        _the_chat_is_called(graph)
        added = graph.post(f"{CHAT_PATH}/members").mock(
            return_value=httpx.Response(
                429, headers={"Retry-After": "60"}, json=_error("TooManyRequests", "four a minute")
            )
        )

        message = await _refused("teams_add_chat_member", **ADD_PRIYA)

        assert "60 seconds" in message and "not sooner" in message
        assert added.call_count == 1

    @pytest.mark.parametrize(
        ("tool", "arguments", "change"),
        [
            ("teams_add_chat_member", ADD_PRIYA, "POST"),
            ("teams_remove_chat_member", REMOVE_TOM, "DELETE"),
        ],
        ids=["addition", "removal"],
    )
    async def test_it_does_not_change_the_members_again_before_they_are_checked(
        self, graph: respx.MockRouter, tool: str, arguments: Row, change: str
    ) -> None:
        _the_chat_is_called(graph)
        _tom_is_a_member(graph)
        changed = graph.route(method=change, path__regex=rf".*{re.escape(CHAT_ID)}/members.*")
        _ = changed.mock(return_value=httpx.Response(500, json=_error("InternalServerError", "x")))

        message = await _refused(tool, **arguments)

        assert "does not know if Microsoft 365 made the change" in message
        assert "use teams_list_chat_members" in message
        assert changed.call_count == 1

    async def test_it_does_not_change_a_meeting_that_microsoft_does_not_show_and_asks_nobody(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/onlineMeetings").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(mia, "teams_update_meeting", **MOVE_MEETING)

        assert "has no meeting with this handle that the signed-in user can see" in message
        assert "deleted" not in message
        assert mia.asked == [] and writes.call_count == 0

    async def test_it_does_not_change_a_meeting_that_microsoft_cannot_find_at_the_change(
        self, graph: respx.MockRouter
    ) -> None:
        _the_meeting_is(graph, _meeting())
        _ = graph.patch(MEETING_PATH).mock(
            return_value=httpx.Response(404, json=_error("NotFound", "no meeting"))
        )

        message = await _refused("teams_update_meeting", **MOVE_MEETING)

        assert "No meeting was changed." in message
        assert "probably deleted it" in message

    async def test_it_reports_a_meeting_that_was_deleted_a_moment_before_its_deletion(
        self, graph: respx.MockRouter
    ) -> None:
        _the_meeting_is(graph, _meeting())
        _ = graph.delete(MEETING_PATH).mock(
            return_value=httpx.Response(404, json=_error("NotFound", "gone"))
        )
        mia = Person()

        message = await _refused_by(mia, "teams_delete_meeting", **DELETE_MEETING)

        assert len(mia.asked) == 1
        assert "did not find this meeting" in message and "probably deleted it" in message
        assert "teams_read_meeting" in message

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.Response(500, json=_error("InternalServerError", "boom")),
            httpx.ReadTimeout("no answer in time"),
            httpx.Response(200, text="<html>x</html>", headers={"content-type": "text/html"}),
        ],
        ids=["internal-error", "timeout", "unreadable-answer"],
    )
    async def test_it_asks_mia_again_and_advises_one_retry_when_a_rename_fails(
        self, graph: respx.MockRouter, failure: httpx.Response | Exception
    ) -> None:
        rename = graph.patch(CHAT_PATH)
        _ = (
            rename.mock(side_effect=failure)
            if isinstance(failure, Exception)
            else rename.mock(return_value=failure)
        )
        mia = Person()

        first = await _refused_by(mia, "teams_rename_chat", **RENAME)
        second = await _refused_by(mia, "teams_rename_chat", **RENAME)

        assert len(mia.asked) == 2
        assert "Retry once" in first and "Retry once" in second
        assert rename.call_count == 2

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.Response(500, json=_error("InternalServerError", "boom")),
            httpx.ReadTimeout("no answer in time"),
            httpx.Response(200, text="<html>x</html>", headers={"content-type": "text/html"}),
        ],
        ids=["internal-error", "timeout", "unreadable-answer"],
    )
    async def test_it_reports_an_attendance_that_microsoft_fails_to_read_as_unreadable(
        self, graph: respx.MockRouter, failure: httpx.Response | Exception
    ) -> None:
        _the_meeting_is(graph, _meeting())
        reports = graph.get(f"{MEETING_PATH}/attendanceReports")
        _ = (
            reports.mock(side_effect=failure)
            if isinstance(failure, Exception)
            else reports.mock(return_value=failure)
        )

        message = await _refused("teams_read_meeting", meeting_uri=MEETING_URI)

        assert "failed internally" in message and "Retry once" in message


class TestAChatAndAMeetingThatTeamsAccepts:
    async def test_it_refuses_a_chat_with_mia_alone_and_asks_nobody(
        self, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        writes = _writes(graph)
        mia = Person()
        mia_alone = {"user_id": SIGNED_IN_USER_ID, "name": "Ada Lovelace"}

        message = await _refused_by(
            mia, "teams_create_chat", chat_type="group", topic="Notes", members=[mia_alone]
        )

        assert "A chat needs at least one other person" in message
        assert mia.asked == [] and writes.call_count == 0

    async def test_it_gives_a_one_to_one_chat_no_title_and_asks_nobody(
        self, graph: respx.MockRouter
    ) -> None:
        mia = Person()

        message = await _refused_by(
            mia, "teams_create_chat", chat_type="oneOnOne", topic="Launch", members=[ANNA]
        )

        assert "allows a topic only on a group chat" in message
        assert mia.asked == [] and not graph.calls

    @pytest.mark.parametrize(
        ("title", "problem"),
        [("Launch: Phase 1", "should match pattern"), ("x" * 251, "at most 250 characters")],
        ids=["colon", "251-characters"],
    )
    async def test_it_refuses_a_title_that_teams_does_not_accept(
        self, graph: respx.MockRouter, title: str, problem: str
    ) -> None:
        mia = Person()

        message = await _refused_by(mia, "teams_create_chat", **{**NEW_CHAT, "topic": title})

        assert problem in message
        assert mia.asked == [] and not graph.calls

    async def test_it_accepts_a_title_of_exactly_250_characters(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_create_chat-group")
        title = "x" * 250
        mia = Person()

        _ = await call("teams_create_chat", person=mia, **{**NEW_CHAT, "topic": title})

        assert _uncalled(routes) == []
        assert len(mia.asked) == 1
        assert _body(routes[("POST", "/chats")])["topic"] == title

    async def test_it_removes_nobody_who_is_not_a_member(self, graph: respx.MockRouter) -> None:
        _ = graph.get(f"{CHAT_PATH}/members/{TOM_MEMBERSHIP}").mock(
            return_value=httpx.Response(404, json=_error("NotFound", "no member"))
        )
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(mia, "teams_remove_chat_member", **REMOVE_TOM)

        assert "has no member with this `membership_id` in this chat" in message
        assert "Nobody was removed." in message
        assert mia.asked == [] and writes.call_count == 0

    @pytest.mark.parametrize(
        ("tool", "arguments", "verb"),
        [
            ("teams_update_meeting", MOVE_MEETING, "changes"),
            ("teams_delete_meeting", DELETE_MEETING, "deletes"),
        ],
        ids=["move", "delete"],
    )
    async def test_it_changes_only_a_meeting_that_mia_organizes(
        self, graph: respx.MockRouter, tool: str, arguments: Row, verb: str
    ) -> None:
        _the_meeting_is(graph, _meeting(organizer=OTHER_USER_ID))
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(mia, tool, **arguments)

        assert f"This tool {verb} only a meeting that the signed-in user organizes." in message
        assert mia.asked == [] and writes.call_count == 0

    async def test_it_refuses_a_meeting_that_ends_before_it_starts_and_asks_nobody(
        self, graph: respx.MockRouter
    ) -> None:
        mia = Person()

        message = await _refused_by(
            mia,
            "teams_create_meeting",
            **{
                **NEW_MEETING,
                "starts_at": "2026-03-02T14:00:00Z",
                "ends_at": "2026-03-02T13:00:00Z",
            },
        )

        assert "A meeting must end after it starts." in message
        assert mia.asked == [] and not graph.calls

    async def test_it_says_the_attendance_is_not_ready_for_a_meeting_that_just_ended(
        self, graph: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _the_clock_reads(monkeypatch, datetime(2026, 2, 10, 15, 10, tzinfo=UTC))
        _the_meeting_is(graph, _meeting())
        _ = graph.get(f"{MEETING_PATH}/attendanceReports").mock(
            return_value=httpx.Response(200, json={"value": []})
        )

        result = await call("teams_read_meeting", meeting_uri=MEETING_URI)

        assert result["status"] == "not_ready"
        assert result["newest_report_attendance"] == []

    async def test_it_says_that_a_meeting_has_no_attendance_report_hours_after_it_ended(
        self, graph: respx.MockRouter
    ) -> None:
        _the_meeting_is(graph, _meeting())
        _ = graph.get(f"{MEETING_PATH}/attendanceReports").mock(
            return_value=httpx.Response(200, json={"value": []})
        )

        result = await call("teams_read_meeting", meeting_uri=MEETING_URI)

        assert result["status"] == "no_report"
        assert result["newest_report_attendance"] == []


class TestNothingChangesUnlessMiaClearlyAgrees:
    @pytest.mark.parametrize(("tool", "arguments", "nothing"), EVERY_PROPOSAL)
    async def test_it_changes_nothing_when_mia_declines(
        self, graph: respx.MockRouter, tool: str, arguments: Row, nothing: str
    ) -> None:
        writes = _everything_is_readable(graph)
        mia = Person(approval="no")

        message = await _refused_by(mia, tool, **arguments)

        assert nothing in message and NOT_AGREED in message
        assert len(mia.asked) == 1
        assert writes.call_count == 0

    @pytest.mark.parametrize(("tool", "arguments", "nothing"), EVERY_PROPOSAL)
    async def test_it_changes_nothing_when_the_chat_program_answers_the_question_with_an_error(
        self, graph: respx.MockRouter, tool: str, arguments: Row, nothing: str
    ) -> None:
        writes = _everything_is_readable(graph)

        message = await _refused_by(Person(approval="unanswered"), tool, **arguments)

        assert nothing in message
        assert "received no answer" in message and "can make the same request again" in message
        assert writes.call_count == 0

    async def test_it_creates_no_chat_when_the_chat_program_cannot_show_a_question(
        self, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        writes = _writes(graph)

        message = await _call_from_a_client_that_cannot_ask("teams_create_chat", **NEW_CHAT)

        assert "No chat was created." in message
        assert "their client cannot ask them to agree" in message
        assert "do this task in the Microsoft 365 app" in message
        assert writes.call_count == 0


class TestAChatProgramOfTheNewerKind:
    @pytest.mark.parametrize(("tool", "arguments", "nothing"), EVERY_PROPOSAL)
    async def test_it_makes_an_approved_change_once_when_the_question_comes_in_the_answer(
        self, graph: respx.MockRouter, tool: str, arguments: Row, nothing: str
    ) -> None:
        _ = nothing
        writes = _everything_is_readable(graph, _the_writes_are_answered)
        mia = Person()

        _ = await call_on_the_newer_protocol(tool, person=mia, **arguments)

        assert len(mia.asked) == 1
        assert writes.call_count == 1

    @pytest.mark.parametrize(("tool", "arguments", "nothing"), EVERY_PROPOSAL)
    @pytest.mark.parametrize(
        "reply",
        [Person(approval="no"), Says(1), Says("maybe")],
        ids=["declines", "the word for no", "a word that is no choice"],
    )
    async def test_it_changes_nothing_unless_the_answer_is_the_word_for_yes(
        self, graph: respx.MockRouter, tool: str, arguments: Row, nothing: str, reply: Person | Says
    ) -> None:
        writes = _everything_is_readable(graph, _the_writes_are_answered)

        message = await refused_on_the_newer_protocol(tool, person=reply, **arguments)

        assert nothing in message and NOT_AGREED in message
        assert writes.call_count == 0


class TestAReferenceThatTheAssistantMadeUp:
    @pytest.mark.parametrize(
        ("tool", "arguments"),
        [
            ("teams_update_meeting", TOMORROW_AT_15),
            ("teams_delete_meeting", {}),
            ("teams_read_meeting", {}),
        ],
        ids=["move", "delete", "attendance"],
    )
    async def test_it_refuses_a_meeting_reference_that_is_not_one_and_asks_nobody(
        self, graph: respx.MockRouter, tool: str, arguments: Row
    ) -> None:
        mia = Person()

        message = await _refused_by(mia, tool, meeting_uri="Design review", **arguments)

        assert "has exactly one shape" in message and "teams_list_chats" in message
        assert mia.asked == [] and not graph.calls


class TestWhatTeamsDoesNotTakeAsAChange:
    @pytest.mark.parametrize(
        ("arguments", "told"),
        [
            ({}, "received no change"),
            ({"starts_at": "2026-03-02T15:00:00Z"}, "without the other"),
            ({"ends_at": "2026-03-02T15:30:00Z"}, "without the other"),
            (
                {"starts_at": "2026-03-02T15:00:00", "ends_at": "2026-03-02T15:30:00Z"},
                "has no offset",
            ),
        ],
        ids=["no change", "a start alone", "an end alone", "a start with no zone"],
    )
    async def test_it_refuses_a_change_that_teams_cannot_take_and_asks_nobody(
        self, graph: respx.MockRouter, arguments: Row, told: str
    ) -> None:
        mia = Person()

        message = await _refused_by(
            mia, "teams_update_meeting", meeting_uri=MEETING_URI, **arguments
        )

        assert told in message and "No meeting was changed." in message
        assert mia.asked == [] and not graph.calls

    @pytest.mark.parametrize(
        ("times", "told"),
        [
            ({"starts_at": "tomorrow at 14:00"}, "not an ISO-8601 date and time"),
            ({"ends_at": "2026-03-02T14:30:00"}, "has no offset"),
        ],
        ids=["a start that is no time", "an end with no zone"],
    )
    async def test_it_refuses_a_new_meeting_whose_time_teams_cannot_read_and_asks_nobody(
        self, graph: respx.MockRouter, times: Row, told: str
    ) -> None:
        mia = Person()

        message = await _refused_by(mia, "teams_create_meeting", **{**NEW_MEETING, **times})

        assert told in message and "No meeting was created." in message
        assert mia.asked == [] and not graph.calls

    @pytest.mark.parametrize(
        ("tool", "arguments", "told"),
        [
            ("teams_delete_meeting", DELETE_MEETING, "has no meeting with this handle"),
            ("teams_read_meeting", {"meeting_uri": MEETING_URI}, None),
        ],
        ids=["delete", "attendance"],
    )
    async def test_it_does_not_delete_or_read_a_meeting_that_microsoft_does_not_show(
        self, graph: respx.MockRouter, tool: str, arguments: Row, told: str | None
    ) -> None:
        _ = graph.get("/me/onlineMeetings").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        writes = _writes(graph)
        mia = Person()

        if told is None:
            result = await call(tool, person=mia, **arguments)
            assert result["status"] == "meeting_not_found"
        else:
            assert told in await _refused_by(mia, tool, **arguments)
        assert mia.asked == [] and writes.call_count == 0

    async def test_it_gives_no_attendee_list_when_microsoft_answers_the_change_without_one(
        self, graph: respx.MockRouter
    ) -> None:
        _the_meeting_is(graph, _meeting())
        _ = graph.patch(MEETING_PATH).mock(return_value=httpx.Response(200, json=meeting_payload()))

        result = await call(
            "teams_update_meeting", meeting_uri=MEETING_URI, subject="Design review 2"
        )

        assert result["attendee_ids"] is None

    async def test_it_names_a_member_without_a_name_as_such_in_the_question(
        self, graph: respx.MockRouter
    ) -> None:
        _the_chat_is_called(graph)
        _ = graph.get(f"{CHAT_PATH}/members/{TOM_MEMBERSHIP}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "id": TOM_MEMBERSHIP,
                    "displayName": None,
                    "userId": TOM["user_id"],
                },
            )
        )
        writes = _writes(graph)
        mia = Person()

        _ = await call("teams_remove_chat_member", person=mia, **REMOVE_TOM)

        assert mia.asked[0].startswith("Remove a member with no name from the Teams chat 'Launch'")
        assert writes.call_count == 1

    async def test_it_names_a_chat_without_a_title_by_its_members_in_the_question(
        self, graph: respx.MockRouter
    ) -> None:
        _the_chat_is_called(graph, topic=None)
        _ = graph.get(f"{CHAT_PATH}/members").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "@odata.type": "#microsoft.graph.aadUserConversationMember",
                            "id": f"member-{one['name']}",
                            "displayName": one["name"],
                            "userId": one["user_id"],
                        }
                        for one in (ANNA, TOM)
                    ]
                },
            )
        )
        writes = _the_writes_are_answered(graph)
        mia = Person()

        _ = await call("teams_add_chat_member", person=mia, **ADD_PRIYA)

        assert "the Teams chat with 'Anna Meier, Tom Berger'" in mia.asked[0]
        assert writes.call_count == 1

    async def test_it_creates_a_one_to_one_chat_after_mia_approves_it(
        self, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        created = graph.post("/chats").mock(
            return_value=httpx.Response(
                201, json={"id": CHAT_ID, "chatType": "oneOnOne", "topic": None}
            )
        )
        mia = Person()

        result = await call("teams_create_chat", person=mia, chat_type="oneOnOne", members=[TOM])

        assert mia.asked[0].startswith("Create a one-to-one Teams chat with")
        assert TOM["user_id"] in mia.asked[0]
        assert (result["chat_type"], result["topic"]) == ("oneOnOne", None)
        assert _body(created)["chatType"] == "oneOnOne"
        assert sorted(_members_of(_body(created))) == sorted([SIGNED_IN_USER_ID, TOM["user_id"]])

    async def test_it_refuses_a_one_to_one_chat_with_two_people_and_asks_nobody(
        self, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        mia = Person()

        message = await _refused_by(
            mia, "teams_create_chat", chat_type="oneOnOne", members=[ANNA, TOM]
        )

        assert "received 2 people for a one-to-one chat" in message
        assert mia.asked == []
