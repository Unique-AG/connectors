import functools
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import cast
from urllib.parse import unquote

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from mcp.types import EmbeddedResource, TextResourceContents

from tests.conftest import RecordedSleeps
from tests.e2e.test_scenarios import build_server, patch_obo
from tests.graph_fixtures import Json, recorded_json
from tests.tools.conftest import GRAPH_V1

from .support import call, response, serve

type Row = Mapping[str, object]

_ZURICH = "Europe/Zurich"
_MIA: Row = {"name": "Mia Keller", "address": "mia@example.test"}
_ANNA: Row = {"name": "Anna Meier", "address": "anna@example.test"}
_CALENDAR_ID = "AAMkSYNTHETIC-calendar-default"
_ANNA_CALENDAR_ID = "AAMkSYNTHETIC-calendar-anna"
_VIEW = f"/me/calendars/{_CALENDAR_ID}/calendarView"
_REJECTION = {"error": {"code": "ErrorInvalidRequest", "message": "The window is not valid."}}
_OFFSITE = "Offsite agenda review"
_ANNA_EVENT = "AAMkSYNTHETIC-event-anna"
_MASTER = "AAMkSYNTHETIC-event-master"
_TOO_MANY: Json = {
    "status": 429,
    "headers": {"Retry-After": "30"},
    "body": "error.TooManyRequests.json",
}

_MICROSOFT_REFUSES = [
    pytest.param(
        {"status": 401, "body": "error.InvalidAuthenticationToken.json"},
        "sign in to this connector again",
        id="expired-sign-in",
    ),
    pytest.param(
        {"status": 403, "body": "error.accessDenied.json"},
        "Ask a Microsoft 365 administrator to grant the delegated permissions",
        id="no-access",
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
            200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}{_VIEW}?$skiptoken=again"}
        )

    return answer


def _calendar(calendar_id: str, owner: Row, *, can_edit: bool) -> dict[str, object]:
    return {
        "id": calendar_id,
        "name": str(owner["name"]),
        "owner": dict(owner),
        "canEdit": can_edit,
        "canShare": can_edit,
        "canViewPrivateItems": can_edit,
        "isDefaultCalendar": owner == _MIA,
        "isTallyingResponses": True,
        "allowedOnlineMeetingProviders": ["teamsForBusiness"],
        "defaultOnlineMeetingProvider": "teamsForBusiness",
    }


def _event(
    event_id: str,
    subject: str,
    start: str,
    end: str,
    *,
    organizer: Row = _MIA,
) -> dict[str, object]:
    return {
        "id": event_id,
        "subject": subject,
        "bodyPreview": f"About {subject}.",
        "start": {"dateTime": f"{start}.0000000", "timeZone": "UTC"},
        "end": {"dateTime": f"{end}.0000000", "timeZone": "UTC"},
        "isAllDay": False,
        "isCancelled": False,
        "type": "singleInstance",
        "seriesMasterId": None,
        "sensitivity": "normal",
        "showAs": "busy",
        "location": {"displayName": "Room Pilatus"},
        "isOnlineMeeting": False,
        "organizer": {"emailAddress": dict(organizer)},
        "isOrganizer": organizer == _MIA,
        "responseStatus": {
            "response": "organizer" if organizer == _MIA else "notResponded",
            "time": "0001-01-01T00:00:00Z",
        },
        "attendees": [],
        "categories": [],
        "importance": "normal",
        "webLink": "https://outlook.office365.com/owa/?itemid=synthetic",
    }


def _view_of(graph: respx.MockRouter) -> respx.Route:
    mine = _calendar(_CALENDAR_ID, _MIA, can_edit=True)
    _ = graph.get("/me/calendar").mock(return_value=httpx.Response(200, json=mine))
    return graph.get(_VIEW).mock(return_value=httpx.Response(200, json={"value": []}))


def _route(routes: Mapping[tuple[str, str], respx.Route], tail: str) -> respx.Route:
    return next(route for (_method, path), route in routes.items() if path.endswith(tail))


def _list(seen: Row, key: str) -> list[Row]:
    return cast("list[Row]", seen[key])


def _part(parent: Row, key: str) -> Row:
    return cast("Row", parent[key])


def _answers(seen: Row) -> dict[str, object]:
    return {str(one["name"]): one["response"] for one in _list(seen, "attendees")}


def _starts(events: Sequence[Row]) -> list[tuple[str, str]]:
    return [(str(one["subject"]), str(_part(one, "start")["iso"])) for one in events]


def _moment(row: Row, key: str) -> datetime:
    return datetime.fromisoformat(str(_part(row, key)["iso"]))


def _uri(event_id: str) -> str:
    return f"outlook:///events/{_CALENDAR_ID}/{event_id}"


async def _day(**arguments: object) -> Row:
    return await _call(
        "outlook_list_events",
        **({"starts_on": "2026-10-29", "ends_on": "2026-10-29", "time_zone": _ZURICH} | arguments),
    )


@functools.cache
def _server() -> FastMCP[None]:
    return build_server()


async def _input_names(tool: str) -> set[str]:
    async with Client(FastMCPTransport(_server()), mode="legacy") as client:
        listed = {one.name: one for one in await client.list_tools()}
    return set(cast("Row", listed[tool].input_schema["properties"]))


async def _read_attachment(uri: str) -> str:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            answer = await client.call_tool("outlook_read_event_attachment", {"uri": uri})
    resource = cast("EmbeddedResource", answer.content[0]).resource
    return cast("TextResourceContents", resource).text


class TestADayOrAWeek:
    async def test_it_lists_the_meetings_of_a_day_with_their_times_in_zurich(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_events-today")

        seen = await _day()

        assert [key for key, route in routes.items() if not route.called] == []
        assert _part(seen, "window")["time_zone"] == _ZURICH
        assert (_OFFSITE, "2026-10-29T11:00:00+01:00") in _starts(_list(seen, "events"))
        assert ("Daily standup", "2026-10-29T09:15:00+01:00") in _starts(_list(seen, "events"))

    async def test_it_lists_a_moved_date_of_a_weekly_meeting_on_its_own_day_only(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_events-series-exception")

        seen = await _day(
            starts_on="2026-11-09", ends_on="2026-12-07", subject_contains="Weekly design sync"
        )

        (moved,) = [one for one in _list(seen, "events") if one["kind"] == "exception"]
        assert _starts([moved]) == [("Weekly design sync", "2026-11-17T09:00:00+01:00")]
        assert moved["in_series"] is True

    async def test_it_gives_overlapping_meetings_times_that_show_the_clash(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_events-overlap")

        seen = await _day(starts_on="2026-11-03", ends_on="2026-11-03", subject_contains="Overlap")

        first, second = _list(seen, "events")
        assert (first["subject"], second["subject"]) == ("Overlap A", "Overlap B")
        assert _moment(second, "start") < _moment(first, "end")

    async def test_it_tells_a_meeting_that_mia_organizes_from_an_invitation(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_events-today")

        seen = await _day()

        assert [key for key, route in routes.items() if not route.called] == []
        own = {str(one["subject"]): one["owner_is_organizer"] for one in _list(seen, "events")}
        assert (own["Hosting review"], own["Roadmap check"]) == (True, False)

    async def test_it_lists_a_day_with_nothing_on_as_empty_and_complete(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_events-today")
        _ = _route(routes, "/calendarView").mock(
            side_effect=[response({"status": 200, "body": "value.empty.json"})]
        )

        seen = await _day()

        assert (seen["events"], seen["capped"]) == ([], False)

    async def test_a_week_of_40_meetings_is_cut_at_the_default_limit_and_whole_at_a_limit_of_40(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_list_events-week-40")
        by_default = await _day(starts_on="2026-11-23", ends_on="2026-11-27")
        graph.routes.clear()
        _ = serve(graph, "rec-tool-outlook_list_events-week-40-whole")
        in_full = await _day(starts_on="2026-11-23", ends_on="2026-11-27", limit=40)

        assert (len(_list(by_default, "events")), by_default["capped"]) == (25, True)
        assert (len(_list(in_full, "events")), in_full["capped"]) == (40, False)


class TestWhoIsComingAndWhereTheMeetingIs:
    async def _read_meeting(self, graph: respx.MockRouter, cassette: str, subject: str) -> Row:
        _ = serve(graph, cassette)
        found = await _day(starts_on="2026-11-03", ends_on="2026-11-03", subject_contains=subject)
        (listed,) = _list(found, "events")
        return await call("outlook_read_event", uri=listed["uri"], time_zone=_ZURICH)

    async def test_it_shows_what_each_attendee_answered(self, graph: respx.MockRouter) -> None:
        mixed = await self._read_meeting(
            graph, "rec-tool-outlook_read_event-answers-mixed", "Design workshop"
        )
        graph.routes.clear()
        open_ = await self._read_meeting(
            graph, "rec-tool-outlook_read_event-answers-open", "Content review"
        )

        assert _answers(mixed) == {"Anna Meier": "accepted", "Tom Berger": "declined"}
        assert _answers(open_) == {"Anna Meier": "tentativelyAccepted", "Tom Berger": "none"}

    async def test_it_has_no_attendee_filter_so_a_person_is_found_by_reading_the_events(
        self, graph: respx.MockRouter
    ) -> None:
        seen = await self._read_meeting(
            graph, "rec-tool-outlook_read_event-answers-mixed", "Design workshop"
        )

        assert await _input_names("outlook_list_events") == {
            "starts_on",
            "ends_on",
            "time_zone",
            "calendar_ref",
            "subject_contains",
            "cancelled",
            "owner_response",
            "limit",
        }
        assert [one["address"] for one in _list(seen, "attendees")] == [
            "anna@example.test",
            "tom@example.test",
        ]

    async def test_it_opens_the_meeting_of_an_invitation_by_its_subject_with_time_and_attendees(
        self, graph: respx.MockRouter
    ) -> None:
        seen = await self._read_meeting(
            graph, "rec-tool-outlook_read_event-answers-mixed", "Design workshop"
        )

        assert seen["subject"] == "Design workshop"
        assert _part(seen, "start")["iso"] == "2026-11-03T10:00:00+01:00"
        assert [one["name"] for one in _list(seen, "attendees")] == ["Anna Meier", "Tom Berger"]
        assert await _input_names("outlook_read_event") == {"uri", "time_zone"}

    async def test_a_meeting_deleted_after_the_listing_is_reported_as_unread_and_not_as_deleted(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_read_event-agenda")
        _ = next(route for (_m, path), route in routes.items() if "/events/" in path).mock(
            side_effect=[response({"status": 404, "body": "error.itemNotFound.json"})]
        )
        (listed,) = _list(await _day(subject_contains=_OFFSITE), "events")

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_read_event", uri=listed["uri"])

        assert "Report that this tool failed to read the event, never that the meeting" in str(
            refused.value
        )
        assert "list the window again" in str(refused.value)


class TestASharedCalendar:
    async def test_it_lists_the_events_of_a_calendar_that_a_colleague_shared(
        self, graph: respx.MockRouter
    ) -> None:
        shared = _calendar(_ANNA_CALENDAR_ID, _ANNA, can_edit=False)
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json={"id": "me", **_MIA}))
        _ = graph.get("/me/calendars").mock(
            return_value=httpx.Response(200, json={"value": [shared]})
        )
        _ = graph.get(f"/me/calendars/{_ANNA_CALENDAR_ID}").mock(
            return_value=httpx.Response(200, json=shared)
        )
        _ = graph.get(f"/me/calendars/{_ANNA_CALENDAR_ID}/calendarView").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _event(
                            "e1",
                            "Design review",
                            "2026-11-03T10:00:00",
                            "2026-11-03T11:00:00",
                            organizer=_ANNA,
                        )
                    ]
                },
            )
        )

        calendars = await call("outlook_list_calendars")
        (anna,) = _list(calendars, "calendars")
        seen = await _day(starts_on="2026-11-03", ends_on="2026-11-03", calendar_ref=anna["uri"])

        assert _part(_part(seen, "calendar"), "owner")["name"] == "Anna Meier"
        assert _starts(_list(seen, "events")) == [("Design review", "2026-11-03T11:00:00+01:00")]

    async def test_a_calendar_that_is_no_longer_shared_is_reported_as_unreadable_not_as_empty(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/me/calendars/{_ANNA_CALENDAR_ID}").mock(
            return_value=response({"status": 404, "body": "error.itemNotFound.json"})
        )

        with pytest.raises(ToolError) as refused:
            _ = await _day(calendar_ref=f"outlook:///calendars/{_ANNA_CALENDAR_ID}")

        assert "stopped sharing it" in str(refused.value)
        assert "call outlook_list_calendars again" in str(refused.value)


class TestAnAttachmentOfAMeeting:
    async def _agenda(self, graph: respx.MockRouter) -> tuple[str, respx.Route]:
        routes = serve(graph, "rec-tool-outlook_read_event_attachment-agenda")
        (listed,) = _list(await _day(subject_contains=_OFFSITE), "events")
        attachments = await call("outlook_list_event_attachments", uri=listed["uri"])
        (agenda,) = _list(attachments, "attachments")
        return str(agenda["uri"]), _route(
            routes, "/attachments/" + str(agenda["uri"]).rsplit("/", 1)[1]
        )

    async def test_it_reads_the_agenda_attached_to_a_meeting(self, graph: respx.MockRouter) -> None:
        uri, _ = await self._agenda(graph)

        text = await _read_attachment(uri)

        assert text == "Offsite agenda.\nMorning: workshop. Afternoon: review.\n"

    @pytest.mark.parametrize(
        ("attachment", "told"),
        [
            pytest.param(
                {"@odata.type": "#microsoft.graph.itemAttachment", "name": "Mail", "size": 100},
                "open the attached item in Outlook",
                id="an-outlook-message",
            ),
            pytest.param(
                {
                    "@odata.type": "#microsoft.graph.referenceAttachment",
                    "name": "Link",
                    "size": 100,
                },
                "open the link from the event in Outlook",
                id="a-link-to-cloud-storage",
            ),
            pytest.param(
                {"@odata.type": "#microsoft.graph.fileAttachment", "name": "agenda.pdf"},
                "open the event in Outlook",
                id="a-file-without-a-reported-size",
            ),
            pytest.param(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "agenda.pdf",
                    "size": 10_485_761,
                },
                "cannot return a file this large",
                id="a-file-one-byte-above-the-limit",
            ),
        ],
    )
    async def test_it_names_an_attachment_it_cannot_give_and_shows_no_content_of_it(
        self, graph: respx.MockRouter, attachment: dict[str, object], told: str
    ) -> None:
        uri, route = await self._agenda(graph)
        described = recorded_json("rec-tool-outlook_read_event_attachment-agenda.04")
        _ = route.mock(return_value=httpx.Response(200, json=described | attachment))

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_read_event_attachment", uri=uri)

        assert told in str(refused.value)
        assert "contentBytes" not in str(refused.value)

    async def test_it_reads_a_file_that_microsoft_reports_at_exactly_the_size_limit(
        self, graph: respx.MockRouter
    ) -> None:
        uri, route = await self._agenda(graph)
        described = recorded_json("rec-tool-outlook_read_event_attachment-agenda.04")
        full = recorded_json("rec-tool-outlook_read_event_attachment-agenda.05")
        _ = route.mock(
            side_effect=[
                httpx.Response(200, json=described | {"size": 10_485_760}),
                httpx.Response(200, json=full | {"size": 10_485_760}),
            ]
        )

        text = await _read_attachment(uri)

        assert text.startswith("Offsite agenda.")

    async def test_an_attachment_that_arrives_empty_is_reported_as_a_fault_of_microsoft(
        self, graph: respx.MockRouter
    ) -> None:
        uri, route = await self._agenda(graph)
        described = recorded_json("rec-tool-outlook_read_event_attachment-agenda.04")
        _ = route.mock(
            side_effect=[httpx.Response(200, json=described), httpx.Response(200, json=described)]
        )

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_read_event_attachment", uri=uri)

        assert "sent no content for this attachment" in str(refused.value)
        assert "Ask for this attachment again later" in str(refused.value)
        assert "tell the user to open the event in Outlook" in str(refused.value)


class TestMicrosoftCannotReadTheCalendar:
    @pytest.mark.parametrize(("answer", "told"), _MICROSOFT_REFUSES)
    async def test_a_refusal_of_microsoft_is_explained_and_lists_no_meeting(
        self, graph: respx.MockRouter, answer: Json, told: str
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_events-today")
        _ = _route(routes, "/calendarView").mock(side_effect=[response(answer)])

        with pytest.raises(ToolError) as refused:
            _ = await _day()

        assert told in str(refused.value)

    async def test_a_busy_microsoft_at_every_try_asks_to_wait_30_seconds_and_not_sooner(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_events-today")
        _ = _route(routes, "/calendarView").mock(side_effect=_reply(_TOO_MANY))

        with pytest.raises(ToolError) as refused:
            _ = await _day()

        assert "asked to be left alone for 30 seconds. Retry after that, not sooner." in str(
            refused.value
        )
        assert retry_sleeps.delays == [30, 30, 30]

    async def test_a_rejected_question_gives_the_reason_and_says_it_fails_again(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_events-today")
        _ = _route(routes, "/calendarView").mock(side_effect=_rejection())

        with pytest.raises(ToolError) as refused:
            _ = await _day()

        assert 'gave this reason: "The window is not valid."' in str(refused.value)
        assert "will fail the same way" in str(refused.value)

    @pytest.mark.parametrize(
        ("fault", "told"),
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
    async def test_a_calendar_that_cannot_be_read_to_the_end_is_not_reported_as_empty(
        self, graph: respx.MockRouter, fault: Fault, told: str
    ) -> None:
        _ = _view_of(graph).mock(side_effect=fault)

        with pytest.raises(ToolError) as refused:
            _ = await _day()

        assert told in str(refused.value)
        assert "Retry once" in str(refused.value)

    async def test_one_busy_answer_is_waited_out_inside_the_same_call(
        self, graph: respx.MockRouter, retry_sleeps: RecordedSleeps
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_events-today")
        _ = _route(routes, "/calendarView").mock(
            side_effect=[
                response(_TOO_MANY),
                response(
                    {
                        "status": 200,
                        "response_json": recorded_json("rec-tool-outlook_list_events-today.02"),
                    }
                ),
            ]
        )

        seen = await _day()

        assert (_OFFSITE, "2026-10-29T11:00:00+01:00") in _starts(_list(seen, "events"))
        assert retry_sleeps.delays == [30]


class TestAWindowNamedBackwards:
    async def test_it_reads_nothing_and_says_which_bound_goes_first(
        self, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _day(starts_on="2026-11-06", ends_on="2026-11-04")

        assert "Put the earlier bound in `starts_on`" in str(refused.value)
        assert graph.calls.call_count == 0

    async def test_the_corrected_window_lists_the_meetings(self, graph: respx.MockRouter) -> None:
        _ = serve(graph, "rec-tool-outlook_list_events-today")

        seen = await _day(starts_on="2026-10-28", ends_on="2026-10-29")

        assert (_OFFSITE, "2026-10-29T11:00:00+01:00") in _starts(_list(seen, "events"))

    @pytest.mark.parametrize(
        ("tool", "arguments"),
        [
            pytest.param("outlook_list_event_instances", {"uri": _uri(_ANNA_EVENT)}, id="series"),
            pytest.param("outlook_list_group_events", {"group_id": "team-1"}, id="team"),
            pytest.param("outlook_list_reminders", {}, id="reminders"),
        ],
    )
    async def test_a_series_or_a_team_calendar_is_not_read_with_a_backwards_window(
        self, graph: respx.MockRouter, tool: str, arguments: Row
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, starts_on="2026-11-06", ends_on="2026-11-04", **arguments)

        assert "falls before `starts_on`" in str(refused.value)
        assert graph.calls.call_count == 0


class TestAMeetingThatRepeats:
    async def test_it_lists_the_dates_of_a_series_inside_the_window(
        self, graph: respx.MockRouter
    ) -> None:
        serve(graph, "rec-tool-outlook_list_event_instances-standup")
        standup = _list(await _day(subject_contains="Daily standup"), "events")[0]

        seen = await call(
            "outlook_list_event_instances",
            uri=standup["series_master_uri"],
            starts_on="2026-10-29",
            ends_on="2026-10-30",
            time_zone=_ZURICH,
        )

        dates = [str(_part(one, "start")["iso"])[:10] for one in _list(seen, "events")]
        assert dates[:2] == ["2026-10-29", "2026-10-30"]
        assert {one["in_series"] for one in _list(seen, "events")} == {True}

    async def test_a_meeting_that_does_not_repeat_is_refused_with_the_way_to_read_it(
        self, graph: respx.MockRouter
    ) -> None:
        serve(graph, "rec-tool-outlook_read_event-agenda")
        (single,) = _list(await _day(subject_contains=_OFFSITE), "events")

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_list_event_instances",
                uri=single["uri"],
                starts_on="2026-10-29",
                ends_on="2026-11-30",
            )

        assert "not part of a recurring series" in str(refused.value)
        assert "call outlook_read_event with the same `uri`" in str(refused.value)

    async def test_a_series_that_cannot_be_read_is_reported_as_unread_and_not_as_ended(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_event_instances-standup")
        standup = _list(await _day(subject_contains="Daily standup"), "events")[0]
        master = next(
            route
            for (_m, path), route in routes.items()
            if path.endswith(
                str(standup["series_master_uri"]).rsplit("/", 1)[1].replace("%3D", "=")
            )
        )
        _ = master.mock(side_effect=[response({"status": 404, "body": "error.itemNotFound.json"})])

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "outlook_list_event_instances",
                uri=standup["series_master_uri"],
                starts_on="2026-10-29",
                ends_on="2026-11-30",
            )

        assert "failed to read the series" in str(refused.value)
        assert "Do not report that the series ended" in str(refused.value)


class TestRemindersAndGroups:
    async def test_it_lists_a_reminder_with_the_time_when_it_fires(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="GET", path__startswith="/me/reminderView").mock(
            return_value=response(
                {
                    "status": 200,
                    "response_json": recorded_json("rec-tool-outlook_list_reminders-today.01"),
                }
            )
        )

        seen = await call(
            "outlook_list_reminders",
            starts_on="2026-10-29",
            ends_on="2026-10-29",
            time_zone=_ZURICH,
        )

        (reminder,) = _list(seen, "reminders")
        assert reminder["subject"] == "Submit the expense report"
        assert _part(reminder, "starts")["iso"] == "2026-10-29T16:00:00+01:00"
        assert _part(reminder, "fires_at")["iso"] == "2026-10-29T15:45:00+01:00"

    async def test_it_shows_the_calendars_by_group_and_marks_the_own_ones(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_calendar_groups-all")
        groups_of_calendars = [r for (_m, path), r in routes.items() if path.endswith("/calendars")]
        anna = _calendar(_ANNA_CALENDAR_ID, _ANNA, can_edit=False)
        _ = groups_of_calendars[1].mock(return_value=httpx.Response(200, json={"value": [anna]}))

        seen = await call("outlook_list_calendar_groups")

        groups = _list(seen, "groups")
        mine = {str(one["name"]): one["is_mine"] for g in groups for one in _list(g, "calendars")}
        assert mine["Anna Meier"] is False
        assert mine["Calendar"] is True


_WINDOW = {"starts_on": "2026-11-06", "ends_on": "2026-11-06"}

_MADE_UP_LINKS = [
    pytest.param(
        "outlook_read_event", {"uri": "Launch review"}, "takes a `uri` handle", id="meeting"
    ),
    pytest.param(
        "outlook_list_event_attachments",
        {"uri": "Launch review"},
        "takes the `uri` of an event",
        id="attachments",
    ),
    pytest.param(
        "outlook_list_event_instances",
        {"uri": "Launch review"} | _WINDOW,
        "`uri` is not an event handle",
        id="series",
    ),
    pytest.param(
        "outlook_read_event_attachment",
        {"uri": "agenda.pdf"},
        "takes the `uri` of an attachment",
        id="attachment",
    ),
    pytest.param(
        "outlook_list_events",
        {"calendar_ref": "Calendar"} | _WINDOW,
        "`calendar_ref` is not a calendar handle",
        id="calendar",
    ),
]

_UNKNOWN_ZONES = [
    pytest.param(
        "outlook_read_event", {"uri": _uri(_ANNA_EVENT)}, "has no such name", id="meeting"
    ),
    pytest.param("outlook_list_events", _WINDOW, "cannot resolve the name", id="day"),
    pytest.param(
        "outlook_list_event_instances",
        {"uri": _uri(_MASTER)} | _WINDOW,
        "cannot resolve `time_zone`",
        id="series",
    ),
    pytest.param(
        "outlook_list_group_events",
        {"group_id": "team-1"} | _WINDOW,
        "cannot resolve the name",
        id="team",
    ),
    pytest.param("outlook_list_reminders", _WINDOW, "cannot resolve the name", id="reminders"),
]


class TestALinkThatTheAssistantMadeUp:
    @pytest.mark.parametrize(("tool", "arguments", "told"), _MADE_UP_LINKS)
    async def test_it_reads_nothing_and_says_which_link_to_use(
        self, graph: respx.MockRouter, tool: str, arguments: Row, told: str
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, **arguments)

        assert told in str(refused.value)
        assert graph.calls.call_count == 0

    @pytest.mark.parametrize(("tool", "arguments", "told"), _UNKNOWN_ZONES)
    async def test_a_time_zone_that_does_not_exist_is_not_guessed(
        self, graph: respx.MockRouter, tool: str, arguments: Row, told: str
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _call(tool, time_zone="Atlantis/Nowhere", **arguments)

        assert told in str(refused.value)
        assert graph.calls.call_count == 0


class TestTheRepeatRuleOfAMeeting:
    async def test_it_shows_the_weekly_rule_and_how_it_ends(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-outlook_read_event-series-master")
        (listed,) = _list(
            await _day(
                starts_on="2026-11-09", ends_on="2026-11-09", subject_contains="Weekly design sync"
            ),
            "events",
        )

        seen = await call("outlook_read_event", uri=listed["series_master_uri"])

        assert [key for key, route in routes.items() if not route.called] == []
        recurrence = _part(seen, "recurrence")
        assert _part(recurrence, "pattern")["kind"] == "weekly"
        assert _part(recurrence, "pattern")["days_of_week"] == ["monday"]
        assert _part(recurrence, "range")["kind"] == "numbered"
        assert _part(recurrence, "range")["number_of_occurrences"] == 6

    async def test_a_meeting_that_does_not_repeat_shows_no_rule(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-outlook_read_event-agenda")
        (listed,) = _list(await _day(subject_contains=_OFFSITE), "events")

        seen = await call("outlook_read_event", uri=listed["uri"])

        assert seen["recurrence"] is None

    async def test_one_date_of_a_series_is_sent_to_the_series_and_not_listed(
        self, graph: respx.MockRouter
    ) -> None:
        date = _event(_ANNA_EVENT, "Team sync", "2026-11-05T09:00:00", "2026-11-05T09:30:00") | {
            "type": "occurrence",
            "seriesMasterId": _MASTER,
        }
        _ = graph.get("/me/calendar").mock(
            return_value=httpx.Response(200, json=_calendar(_CALENDAR_ID, _MIA, can_edit=True))
        )
        _ = graph.get(f"/me/calendars/{_CALENDAR_ID}/events/{_ANNA_EVENT}").mock(
            return_value=httpx.Response(200, json=date)
        )

        with pytest.raises(ToolError) as refused:
            _ = await _call("outlook_list_event_instances", uri=_uri(_ANNA_EVENT), **_WINDOW)

        assert "is one date of a recurring series" in str(refused.value)
        assert _uri(_MASTER) in str(refused.value)


class TestMeetingsThatWereCancelled:
    async def test_the_cancelled_ones_are_left_out_on_request(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-outlook_list_events-not-cancelled")

        seen = await _day(starts_on="2026-10-29", ends_on="2026-10-30", cancelled=False)

        view = next(route for (_m, path), route in routes.items() if path.endswith("/calendarView"))
        assert "isCancelled eq false" in unquote(str(view.calls.last.request.url))
        assert seen["capped"] is False

    async def test_a_cancelled_meeting_is_asked_for_by_name(self, graph: respx.MockRouter) -> None:
        view = _view_of(graph)

        _ = await _day(cancelled=True)

        assert "isCancelled eq true" in unquote(str(view.calls.last.request.url))


class TestATimeThatMicrosoftGivesInAStrangeForm:
    @pytest.mark.parametrize(
        ("start", "shown"),
        [
            pytest.param({"dateTime": "soon", "timeZone": "UTC"}, ("soon", None), id="unreadable"),
            pytest.param(
                {"dateTime": "2026-11-06T09:00:00.0000000", "timeZone": "Mars/Base"},
                ("2026-11-06T09:00:00.0000000", None),
                id="unknown-zone",
            ),
            pytest.param(None, None, id="missing"),
        ],
    )
    async def test_it_is_shown_as_written_and_never_as_a_guessed_time(
        self, graph: respx.MockRouter, start: Row | None, shown: tuple[str, None] | None
    ) -> None:
        odd = _event(_ANNA_EVENT, "Team sync", "2026-11-06T09:00:00", "2026-11-06T09:30:00") | {
            "start": start,
            "body": None,
        }
        _ = graph.get("/me/calendar").mock(
            return_value=httpx.Response(200, json=_calendar(_CALENDAR_ID, _MIA, can_edit=True))
        )
        _ = graph.get(f"/me/calendars/{_CALENDAR_ID}/events/{_ANNA_EVENT}").mock(
            return_value=httpx.Response(200, json=odd)
        )

        seen = await call("outlook_read_event", uri=_uri(_ANNA_EVENT))

        if shown is None:
            assert seen["start"] is None
        else:
            assert (_part(seen, "start")["local"], _part(seen, "start")["iso"]) == shown
        assert seen["body"] is None


class TestACalendarWithNoOwner:
    async def test_it_is_listed_with_no_owner(self, graph: respx.MockRouter) -> None:
        bare = _calendar(_ANNA_CALENDAR_ID, _ANNA, can_edit=False)
        del bare["owner"]
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json={"id": "me", **_MIA}))
        _ = graph.get("/me/calendars").mock(
            return_value=httpx.Response(200, json={"value": [bare]})
        )

        calendars = await call("outlook_list_calendars")

        (row,) = _list(calendars, "calendars")
        assert (row["name"], row["owner"]) == ("Anna Meier", None)
