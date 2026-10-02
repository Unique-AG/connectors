import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.seam import READ_ONLY, REQUESTABLE_PERMISSIONS
from office_365_mcp.tools import PRESETS, TOOL_NAMES
from office_365_mcp.tools import outlook_list_group_events as lister

from .conftest import GRAPH_V1

_GROUP_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_VIEW = f"/groups/{_GROUP_ID}/calendarView"

_SUMMER_MONDAY = date(2026, 7, 6)
_SUMMER_SUNDAY = date(2026, 7, 12)
_MARCH_MONDAY = date(2026, 3, 2)
_MARCH_SUNDAY = date(2026, 3, 8)
_ZURICH = "Europe/Zurich"

_ADA = {"name": "Ada Lovelace", "address": "ada@example.invalid"}

_RETRY = "If you call this tool again with the same arguments, the call will fail the same way."

_FIELDS_ASKED_FOR = [
    "subject",
    "bodyPreview",
    "start",
    "end",
    "isAllDay",
    "isCancelled",
    "type",
    "seriesMasterId",
    "location",
    "onlineMeeting",
    "organizer",
    "webLink",
]


def _event_payload(
    event_id: str,
    *,
    subject: str | None = "Team sync",
    start: str = "2026-07-06T13:00:00.0000000",
    end: str = "2026-07-06T14:00:00.0000000",
    time_zone: str | None = "UTC",
    is_cancelled: bool | None = False,
    event_type: str | None = "occurrence",
    series_master_id: str | None = "AAMkAGI2SYNTHETIC-series-0001=",
) -> dict[str, object]:
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
        "location": {"displayName": "Room 3"},
        "onlineMeeting": {"joinUrl": "https://teams.microsoft.invalid/l/meetup-join/synthetic"},
        "organizer": {"emailAddress": dict(_ADA)},
        "webLink": "https://outlook.office365.invalid/owa/?itemid=synthetic",
    }


def _page(*events: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(events)}
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
    return graph.get(_VIEW).mock(return_value=_page(_event_payload("AAMkAGI2SYNTHETIC-0001=")))


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    lister.register(mcp, transport)
    tool = await mcp.get_tool(lister.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


def _properties(tool: Tool) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])


def _unguarded(tool: Tool) -> list[str]:
    schemas = json.dumps([tool.parameters, tool.output_schema], ensure_ascii=False)
    prose = [tool.description or "", *re.findall(r'"description": "((?:[^"\\]|\\.)*)"', schemas)]
    held = frozenset(TOOL_NAMES).intersection(
        *(names for names in PRESETS.values() if tool.name in names)
    )
    mention = re.compile(rf"\b(?:{'|'.join(TOOL_NAMES)})\b")
    offenders: list[str] = []
    for sentence in (s for text in prose for s in re.split(r"(?<=[.!?])\s+|\n\s*-\s+", text)):
        outside = set(mention.findall(sentence)) - held
        guard = sentence.split(",", 1)[0]
        if outside and not (
            guard.startswith("If this deployment exposes ")
            and outside <= set(mention.findall(guard))
        ):
            offenders.append(sentence)
    return offenders


class TestTheRequestItSends:
    async def test_the_group_is_addressed_by_the_id_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter, view: respx.Route
    ) -> None:
        mine = graph.get("/me/calendar/calendarView")

        _ = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert view.call_count == 1
        assert mine.call_count == 0, "a group calendar is not the calendar of the signed-in user"

    async def test_both_bounds_carry_the_offset_of_the_zone_that_was_asked_for(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_group_events(
            client,
            group_id=_GROUP_ID,
            starts_on=_SUMMER_MONDAY,
            ends_on=_SUMMER_SUNDAY,
            time_zone=_ZURICH,
            limit=25,
        )

        params = view.calls.last.request.url.params
        assert params["startDateTime"] == "2026-07-06T00:00:00+02:00"
        assert params["endDateTime"] == "2026-07-13T00:00:00+02:00"

    async def test_a_moment_with_an_offset_keeps_it_and_a_moment_without_one_takes_the_zone(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_group_events(
            client,
            group_id=_GROUP_ID,
            starts_on=datetime.fromisoformat("2026-07-06T09:30:00"),
            ends_on=datetime.fromisoformat("2026-07-06T17:00:00+00:00"),
            time_zone=_ZURICH,
            limit=25,
        )

        params = view.calls.last.request.url.params
        assert params["startDateTime"] == "2026-07-06T09:30:00+02:00"
        assert params["endDateTime"] == "2026-07-06T19:00:00+02:00"

    async def test_the_end_bound_opens_the_day_after_the_last_one_asked_for(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_MONDAY, limit=25
        )

        params = view.calls.last.request.url.params
        assert params["startDateTime"] == "2026-03-02T00:00:00+00:00"
        assert params["endDateTime"] == "2026-03-03T00:00:00+00:00"

    async def test_it_asks_for_the_group_event_fields_and_nothing_else(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert view.calls.last.request.url.params["$select"].split(",") == _FIELDS_ASKED_FOR

    async def test_it_sends_no_option_the_group_page_does_not_document(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=7
        )

        params = view.calls.last.request.url.params
        assert set(params) == {"startDateTime", "endDateTime", "$select"}, (
            "the group page documents no `$top`, `$orderby` or `$filter` for this view"
        )

    async def test_no_request_asks_exchange_to_render_the_times(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        _ = await lister.list_group_events(
            client,
            group_id=_GROUP_ID,
            starts_on=_SUMMER_MONDAY,
            ends_on=_SUMMER_SUNDAY,
            time_zone=_ZURICH,
            limit=25,
        )

        assert "outlook.timezone" not in view.calls.last.request.headers.get("Prefer", "")


class TestWhatItAnswers:
    @pytest.mark.usefixtures("view")
    async def test_it_reports_the_fields_a_model_triages_on(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        row = answer.events[0]
        assert row.subject == "Team sync"
        assert row.preview == "Agenda attached."
        assert row.all_day is False
        assert row.cancelled is False
        assert row.kind == "occurrence"
        assert row.in_series is True
        assert row.location == "Room 3"
        assert row.join_url == "https://teams.microsoft.invalid/l/meetup-join/synthetic"
        assert row.organizer is not None
        assert row.organizer.address == "ada@example.invalid"
        assert row.web_link == "https://outlook.office365.invalid/owa/?itemid=synthetic"

    @pytest.mark.usefixtures("view")
    async def test_a_row_carries_no_handle(self, client: GraphServiceClient) -> None:
        answer = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert "uri" not in type(answer.events[0]).model_fields, (
            "outlook_read_event addresses only calendars of the signed-in user"
        )

    @pytest.mark.usefixtures("view")
    async def test_the_rows_are_converted_into_the_zone_that_was_asked_for(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_group_events(
            client,
            group_id=_GROUP_ID,
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

    @pytest.mark.usefixtures("view")
    async def test_the_window_that_was_asked_for_comes_back_with_the_rows(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_group_events(
            client,
            group_id=_GROUP_ID,
            starts_on=_SUMMER_MONDAY,
            ends_on=_SUMMER_SUNDAY,
            time_zone=_ZURICH,
            limit=25,
        )

        assert answer.window.starts_at == "2026-07-06T00:00:00+02:00"
        assert answer.window.ends_at == "2026-07-13T00:00:00+02:00"
        assert answer.window.time_zone == _ZURICH

    async def test_a_single_event_is_not_in_a_series(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(
            return_value=_page(
                _event_payload("AAMkAGI2SYNTHETIC-0002=", event_type="singleInstance")
                | {"seriesMasterId": None}
            )
        )

        answer = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert answer.events[0].kind == "singleInstance"
        assert answer.events[0].in_series is False

    async def test_a_row_with_only_an_id_maps_to_nulls_instead_of_failing(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(return_value=_page({"id": "AAMkAGI2SYNTHETIC-0003="}))

        answer = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        row = answer.events[0]
        assert (row.subject, row.start, row.end, row.kind, row.location) == (
            None,
            None,
            None,
            None,
            None,
        )
        assert (row.join_url, row.organizer, row.web_link) == (None, None, None)
        assert row.in_series is False

    async def test_a_canceled_row_is_flagged_rather_than_dropped(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(return_value=_page(_event_payload("AAMkAGI2SYNTHETIC-0004=", is_cancelled=True)))

        answer = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert [row.cancelled for row in answer.events] == [True]

    async def test_the_order_graph_returned_is_the_order_answered(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(
            return_value=_page(
                _event_payload("AAMkAGI2SYNTHETIC-0005=", start="2026-03-04T11:00:00.0000000"),
                _event_payload("AAMkAGI2SYNTHETIC-0006=", start="2026-03-02T09:00:00.0000000"),
            )
        )

        answer = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert [row.start.iso for row in answer.events if row.start is not None] == [
            "2026-03-04T11:00:00+00:00",
            "2026-03-02T09:00:00+00:00",
        ]

    async def test_the_pages_of_a_window_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_VIEW, params={"$skip": "10"}).mock(
            return_value=_page(_event_payload("AAMkAGI2SYNTHETIC-0008=", subject="Second"))
        )
        graph.get(_VIEW).mock(
            return_value=_page(
                _event_payload("AAMkAGI2SYNTHETIC-0007=", subject="First"),
                next_link=f"{GRAPH_V1}{_VIEW}?$skip=10",
            )
        )

        answer = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert [row.subject for row in answer.events] == ["First", "Second"]
        assert answer.capped is False, "the walk reached the end of the window"

    async def test_a_limit_that_left_more_of_the_window_on_offer_says_capped(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(
            return_value=_page(
                _event_payload("AAMkAGI2SYNTHETIC-0009=", subject="First"),
                _event_payload("AAMkAGI2SYNTHETIC-0010=", subject="Second"),
            )
        )

        answer = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=1
        )

        assert [row.subject for row in answer.events] == ["First"]
        assert answer.capped is True

    async def test_a_window_filled_exactly_by_its_own_end_is_not_capped(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(
            return_value=_page(
                _event_payload("AAMkAGI2SYNTHETIC-0011="),
                _event_payload("AAMkAGI2SYNTHETIC-0012="),
            )
        )

        answer = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=2
        )

        assert len(answer.events) == 2
        assert answer.capped is False

    async def test_an_empty_window_answers_no_rows_and_no_cap(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(return_value=_page())

        answer = await lister.list_group_events(
            client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
        )

        assert answer.events == []
        assert answer.capped is False


class TestWhatItRefuses:
    async def test_a_window_that_runs_backwards_never_reaches_graph(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="backwards"):
            _ = await lister.list_group_events(
                client,
                group_id=_GROUP_ID,
                starts_on=_MARCH_SUNDAY,
                ends_on=_MARCH_MONDAY,
                limit=25,
            )

        assert view.call_count == 0

    @pytest.mark.parametrize(
        "time_zone",
        ["W. Europe Standard Time", "Pacific Standard Time", "Zurich", "+02:00", ""],
    )
    async def test_a_zone_zoneinfo_cannot_resolve_never_reaches_graph(
        self, client: GraphServiceClient, view: respx.Route, time_zone: str
    ) -> None:
        with pytest.raises(ToolError, match="IANA"):
            _ = await lister.list_group_events(
                client,
                group_id=_GROUP_ID,
                starts_on=_MARCH_MONDAY,
                ends_on=_MARCH_SUNDAY,
                time_zone=time_zone,
                limit=25,
            )

        assert view.call_count == 0

    async def test_the_zone_refusal_names_the_default_and_the_etc_gmt_sign(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="`UTC` is the default") as refused:
            _ = await lister.list_group_events(
                client,
                group_id=_GROUP_ID,
                starts_on=_MARCH_MONDAY,
                ends_on=_MARCH_SUNDAY,
                time_zone="+02:00",
                limit=25,
            )

        assert "BEHIND UTC" in str(refused.value)

    @pytest.mark.parametrize(
        ("starts_on", "ends_on", "time_zone"),
        [(_MARCH_SUNDAY, _MARCH_MONDAY, "UTC"), (_MARCH_MONDAY, _MARCH_SUNDAY, "Zurich")],
        ids=["a window that runs backwards", "a zone that does not resolve"],
    )
    async def test_every_refusal_ends_with_the_canonical_retry_sentence(
        self, client: GraphServiceClient, starts_on: date, ends_on: date, time_zone: str
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await lister.list_group_events(
                client,
                group_id=_GROUP_ID,
                starts_on=starts_on,
                ends_on=ends_on,
                time_zone=time_zone,
                limit=25,
            )

        assert str(refused.value).endswith(_RETRY)

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_a_limit_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await lister.list_group_events(
                client,
                group_id=_GROUP_ID,
                starts_on=_MARCH_MONDAY,
                ends_on=_MARCH_SUNDAY,
                limit=limit,
            )


class TestTheSchemaItPublishes:
    async def test_the_group_and_the_window_are_what_a_caller_has_to_supply(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.parameters.get("required", []) == ["group_id", "starts_on", "ends_on"]

    async def test_the_zone_defaults_to_utc_and_the_limit_has_a_floor_and_no_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = _properties(await _registered(transport))

        assert properties["time_zone"]["default"] == "UTC"
        assert properties["limit"]["minimum"] == 1
        assert "maximum" not in properties["limit"]
        assert properties["limit"]["default"] == 25

    async def test_an_empty_group_id_is_refused_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = _properties(await _registered(transport))

        assert properties["group_id"]["minLength"] == 1

    async def test_the_group_id_says_where_it_comes_from(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = _properties(await _registered(transport))

        described = str(properties["group_id"]["description"])
        assert "teams_list_my_teams" in described
        assert "`team_id`" in described

    async def test_no_argument_is_published_that_the_group_page_does_not_document(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = _properties(await _registered(transport))

        assert set(properties) == {"group_id", "starts_on", "ends_on", "time_zone", "limit"}

    def test_the_call_example_names_only_arguments_the_tool_takes(self) -> None:
        assert set(lister.GRAPH_CALL_EXAMPLE) == {"group_id", "starts_on", "ends_on"}

    async def test_the_description_says_that_a_row_cannot_be_opened(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = str(tool.description)
        assert "A row has no `uri`." in described
        assert "No other tool of this connector can open a group event." in described
        assert "outlook_read_event" not in described
        assert "teams_list_my_teams" in described
        assert "does not sort the rows" in described

    async def test_the_description_names_the_tool_for_a_person_only_after_a_guard(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert (
            "If this deployment exposes outlook_list_events, use that tool for the calendars of "
            "a person."
        ) in str(tool.description)

    async def test_every_other_tool_it_names_comes_after_a_guard_that_names_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert _unguarded(tool) == []

    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, "a tool with no annotations joins the write surface"
        assert annotations.read_only_hint is READ_ONLY["readOnlyHint"]

    def test_every_row_field_description_is_between_fifteen_and_sixty_words(self) -> None:
        for name, field in lister.GroupEventSummary.model_fields.items():
            words = len((field.description or "").split())
            assert 15 <= words <= 60, f"GroupEventSummary.{name} has {words} words"

    def test_every_row_field_description_says_when_the_field_is_null(self) -> None:
        for name, field in lister.GroupEventSummary.model_fields.items():
            assert "null" in (field.description or ""), f"GroupEventSummary.{name} is silent"

    def test_the_kind_names_the_three_values_that_a_calendar_view_returns(self) -> None:
        described = lister.GroupEventSummary.model_fields["kind"].description or ""

        for value in ("`singleInstance`", "`occurrence`", "`exception`"):
            assert value in described
        assert "seriesMaster" not in described

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        published = _fields(answer, lister.TOOL_NAME, root=answer)
        assert f"{lister.TOOL_NAME}.window.starts_at" in published
        assert f"{lister.TOOL_NAME}.events[].start.iso" in published
        assert f"{lister.TOOL_NAME}.events[].organizer.address" in published
        undescribed = sorted(
            path
            for path, field in published.items()
            if not cast("Mapping[str, object]", field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"


class TestGraphFailures:
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_group_events(
                client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
            )

    async def test_a_group_microsoft_does_not_know_arrives_as_not_found(
        self, client: GraphServiceClient, view: respx.Route
    ) -> None:
        view.mock(return_value=httpx.Response(404))

        with pytest.raises(GraphNotFound):
            _ = await lister.list_group_events(
                client, group_id=_GROUP_ID, starts_on=_MARCH_MONDAY, ends_on=_MARCH_SUNDAY, limit=25
            )

    def test_the_permission_is_a_calendar_scope_that_the_connector_already_requests(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Calendars.Read",)
        assert set(lister.GRAPH_PERMISSIONS) <= REQUESTABLE_PERMISSIONS

    def test_a_group_that_will_not_resolve_is_answered_with_the_recovery_that_fits(self) -> None:
        assert "teams_list_my_teams" in lister.GRAPH_NOT_FOUND
        assert lister.GRAPH_NOT_FOUND.endswith(_RETRY)
