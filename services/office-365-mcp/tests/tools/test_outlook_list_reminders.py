from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.tools import outlook_list_reminders as lister

from .conftest import GRAPH_V1

_REMINDER_VIEW = r"^https://graph\.microsoft\.com/v1\.0/me/reminderView\("

_MARCH_MONDAY = date(2026, 3, 2)
_MARCH_SUNDAY = date(2026, 3, 8)
_ZURICH = "Europe/Zurich"


def _reminder_payload(
    *,
    subject: str | None = "Plan summer company picnic",
    start: str | None = "2026-03-04T09:00:00.0000000",
    end: str | None = "2026-03-04T10:00:00.0000000",
    fires: str | None = "2026-03-04T08:45:00.0000000",
    location: str | None = "Conf Room 3",
    web_link: str | None = "https://outlook.office365.invalid/owa/?itemid=synthetic",
) -> dict[str, object]:
    def moment(value: str | None) -> dict[str, object] | None:
        return None if value is None else {"dateTime": value, "timeZone": "UTC"}

    return {
        "eventId": "AAMkADNsvSYNTHETIC-event-0001=",
        "changeKey": "SuFHwDRP1EeXJUopWbSLlgAAmBvk2g==",
        "eventSubject": subject,
        "eventWebLink": web_link,
        "eventStartTime": moment(start),
        "eventEndTime": moment(end),
        "eventLocation": None if location is None else {"displayName": location},
        "reminderFireTime": moment(fires),
    }


def _page(*reminders: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(reminders)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _fields(node: object, at: str, *, root: Mapping[str, object]) -> dict[str, object]:
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
def view(graph: respx.MockRouter) -> respx.Route:
    return graph.route(method="GET", url__regex=_REMINDER_VIEW).mock(
        return_value=_page(_reminder_payload())
    )


class TestTheRequestItSends:
    async def test_it_calls_the_documented_function_with_both_bounds_in_utc(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

        assert view.calls.last.request.url.raw_path == (
            b"/v1.0/me/reminderView("
            + b"startDateTime='2026-03-02T00:00:00.0000000',"
            + b"endDateTime='2026-03-09T00:00:00.0000000')"
        )

    async def test_the_two_function_parameters_are_separated_by_a_comma(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

        path = view.calls.last.request.url.raw_path.decode()
        assert "'2026-03-02T00:00:00.0000000',endDateTime=" in path

    async def test_the_end_bound_opens_the_day_after_the_last_one_asked_for(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_MONDAY)

        path = view.calls.last.request.url.raw_path.decode()
        assert "startDateTime='2026-03-02T00:00:00.0000000'" in path
        assert "endDateTime='2026-03-03T00:00:00.0000000'" in path

    async def test_bounds_in_another_zone_reach_graph_as_the_same_instants_in_utc(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_reminders(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, time_zone=_ZURICH
        )

        path = view.calls.last.request.url.raw_path.decode()
        assert "startDateTime='2026-03-01T23:00:00.0000000'" in path
        assert "endDateTime='2026-03-08T23:00:00.0000000'" in path

    async def test_a_moment_with_its_own_offset_keeps_the_instant_it_names(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_reminders(
            client,
            starts_on=datetime.fromisoformat("2026-03-02T09:30:00+05:00"),
            ends_on=datetime.fromisoformat("2026-03-02T17:00:00+05:00"),
            time_zone=_ZURICH,
        )

        path = view.calls.last.request.url.raw_path.decode()
        assert "startDateTime='2026-03-02T04:30:00.0000000'" in path
        assert "endDateTime='2026-03-02T12:00:00.0000000'" in path

    async def test_it_sends_no_query_option_and_no_preference_header(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

        request = view.calls.last.request
        assert request.url.query == b""
        assert "Prefer" not in request.headers


class TestWhatItAnswers:
    @pytest.mark.usefixtures("view")
    async def test_a_row_carries_what_graph_reported_about_the_event_and_its_reminder(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

        row = answer.reminders[0]
        assert row.subject == "Plan summer company picnic"
        assert row.location == "Conf Room 3"
        assert row.web_link == "https://outlook.office365.invalid/owa/?itemid=synthetic"
        assert row.starts is not None
        assert row.starts.local == "2026-03-04T09:00:00.0000000"
        assert row.ends is not None
        assert row.ends.local == "2026-03-04T10:00:00.0000000"
        assert row.fires_at is not None
        assert row.fires_at.local == "2026-03-04T08:45:00.0000000"

    @pytest.mark.usefixtures("view")
    async def test_the_times_are_converted_into_the_zone_that_was_asked_for(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_reminders(
            client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, time_zone=_ZURICH
        )

        row = answer.reminders[0]
        assert row.starts is not None
        assert row.starts.iso == "2026-03-04T10:00:00+01:00"
        assert row.starts.time_zone == "UTC"
        assert row.ends is not None
        assert row.ends.iso == "2026-03-04T11:00:00+01:00"
        assert row.fires_at is not None
        assert row.fires_at.iso == "2026-03-04T09:45:00+01:00"

    async def test_a_row_graph_reported_nothing_on_is_still_listed(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(
            return_value=_page(
                _reminder_payload(
                    subject=None, start=None, end=None, fires=None, location=None, web_link=None
                )
            )
        )

        answer = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

        row = answer.reminders[0]
        assert row.subject is None
        assert row.starts is None
        assert row.ends is None
        assert row.fires_at is None
        assert row.location is None
        assert row.web_link is None

    @pytest.mark.usefixtures("view")
    async def test_no_row_carries_an_event_handle_or_an_event_id(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

        assert set(answer.reminders[0].model_dump()) == {
            "subject",
            "starts",
            "ends",
            "location",
            "web_link",
            "fires_at",
        }

    async def test_the_order_graph_returned_is_the_order_answered(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(
            return_value=_page(
                _reminder_payload(subject="Second"),
                _reminder_payload(subject="First"),
            )
        )

        answer = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

        assert [row.subject for row in answer.reminders] == ["Second", "First"]

    async def test_the_pages_of_a_window_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.route(method="GET", url__regex=_REMINDER_VIEW, params={"$skiptoken": "second"}).mock(
            return_value=_page(_reminder_payload(subject="Second"))
        )
        graph.route(method="GET", url__regex=_REMINDER_VIEW).mock(
            return_value=_page(
                _reminder_payload(subject="First"),
                next_link=f"{GRAPH_V1}/me/reminderView(startDateTime='a',endDateTime='b')"
                + "?$skiptoken=second",
            )
        )

        answer = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

        assert [row.subject for row in answer.reminders] == ["First", "Second"]
        assert answer.capped is False, "the walk reached the end of the window"

    async def test_a_cap_that_left_more_reminders_on_offer_says_capped(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 1)
        graph.route(method="GET", url__regex=_REMINDER_VIEW, params={"$skiptoken": "second"}).mock(
            return_value=_page(_reminder_payload(subject="Second"))
        )
        graph.route(method="GET", url__regex=_REMINDER_VIEW).mock(
            return_value=_page(
                _reminder_payload(subject="First"),
                next_link=f"{GRAPH_V1}/me/reminderView(startDateTime='a',endDateTime='b')"
                + "?$skiptoken=second",
            )
        )

        answer = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

        assert [row.subject for row in answer.reminders] == ["First"]
        assert answer.capped is True

    async def test_a_window_with_no_reminder_answers_an_empty_list_and_no_cap(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(return_value=_page())

        answer = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

        assert answer.reminders == []
        assert answer.capped is False


class TestWhatItRefuses:
    async def test_a_window_that_runs_backwards_never_reaches_graph(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="backwards"):
            _ = await lister.list_reminders(client, starts_on=_MARCH_SUNDAY, ends_on=_MARCH_MONDAY)

        assert view.call_count == 0

    async def test_the_same_date_in_both_bounds_is_one_whole_day(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_MONDAY)

        assert view.call_count == 1

    @pytest.mark.parametrize(
        "time_zone",
        ["W. Europe Standard Time", "Pacific Standard Time", "Zurich", "+02:00", ""],
    )
    async def test_a_zone_zoneinfo_cannot_resolve_never_reaches_graph(
        self, client: GraphServiceClient, view: respx.Route, time_zone: str
    ) -> None:
        with pytest.raises(ToolError, match="IANA"):
            _ = await lister.list_reminders(
                client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, time_zone=time_zone
            )

        assert view.call_count == 0


class TestTheSchemaItPublishes:
    async def test_the_window_is_the_only_thing_a_caller_has_to_supply(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters.get("required", []) == ["starts_on", "ends_on"]
        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert sorted(properties) == ["ends_on", "starts_on", "time_zone"]

    async def test_each_bound_admits_a_date_and_a_moment(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        for bound in ("starts_on", "ends_on"):
            assert tool.parameters["properties"][bound]["anyOf"] == [
                {"type": "string", "format": "date"},
                {"type": "string", "format": "date-time"},
            ], bound

    async def test_the_zone_defaults_to_utc_rather_than_to_a_guess(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters["properties"]["time_zone"]["default"] == "UTC"
        assert tool.parameters["properties"]["time_zone"]["minLength"] == 1

    async def test_the_tool_reads_and_changes_nothing(self, transport: httpx.AsyncClient) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True

    async def test_the_description_names_the_tool_that_lists_the_events(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert "outlook_list_events" in (tool.description or "")
        assert "A row has no event handle" in (tool.description or "")

    async def test_the_description_does_not_claim_which_calendars_the_view_covers(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert "Graph does not say which calendars this view covers" in (tool.description or "")

    async def test_the_link_field_says_why_a_row_has_no_event_handle(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, object]", tool.output_schema)
        published = _fields(answer, lister.TOOL_NAME, root=answer)
        link = cast("Mapping[str, object]", published[f"{lister.TOOL_NAME}.reminders[].web_link"])
        assert "no event handle" in str(link["description"])
        assert "no calendar id" in str(link["description"])

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, object]", tool.output_schema)
        published = _fields(answer, lister.TOOL_NAME, root=answer)
        assert f"{lister.TOOL_NAME}.reminders[].fires_at.iso" in published, (
            "the walk stopped before the nested rows"
        )
        undescribed = sorted(
            path
            for path, field in published.items()
            if not cast("Mapping[str, object]", field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"

    def test_the_call_that_proves_the_permissions_names_a_whole_window(self) -> None:
        assert lister.GRAPH_CALL_EXAMPLE == {"starts_on": "2026-03-02", "ends_on": "2026-03-08"}


class TestGraphFailures:
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_reminders(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY)

    def test_the_permission_is_the_one_microsoft_documents_as_least_privileged(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Calendars.ReadBasic",)
