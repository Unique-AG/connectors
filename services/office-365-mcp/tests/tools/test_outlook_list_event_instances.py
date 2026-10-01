from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.calendar import SUMMARY_FIELDS
from office_365_mcp.shared.handles import CalendarHandle, EventHandle, MailMessageHandle
from office_365_mcp.tools import outlook_list_event_instances as lister

from .conftest import GRAPH_V1

_CALENDAR_ID = "AAMkADAwSYNTHETIC-calendar-default"
_MASTER_ID = "AAMkAGI2SYNTHETIC-series-0001="
_FIRST_ID = "AAMkAGI2SYNTHETIC-immutable-0001="
_SECOND_ID = "AAMkAGI2SYNTHETIC-immutable-0002="
_THIRD_ID = "AAMkAGI2SYNTHETIC-immutable-0003="

_MASTER_URI = EventHandle(_CALENDAR_ID, _MASTER_ID).uri

_CALENDAR_PATH = f"/me/calendars/{_CALENDAR_ID}/events"
_MASTER = f"{_CALENDAR_PATH}/AAMkAGI2SYNTHETIC-series-0001%3D"
_INSTANCES = f"{_MASTER}/instances"
_OCCURRENCE = f"{_CALENDAR_PATH}/AAMkAGI2SYNTHETIC-immutable-0001%3D"

_MARCH_MONDAY = date(2026, 3, 2)
_MARCH_SUNDAY = date(2026, 3, 8)
_SUMMER_MONDAY = date(2026, 7, 6)
_SUMMER_SUNDAY = date(2026, 7, 12)
_ZURICH = "Europe/Zurich"


def _event_payload(
    event_id: str,
    *,
    event_type: str | None = "occurrence",
    series_master_id: str | None = _MASTER_ID,
    start: str = "2026-03-02T13:00:00.0000000",
    end: str = "2026-03-02T14:00:00.0000000",
) -> dict[str, object]:
    return {
        "id": event_id,
        "subject": "Pricing review",
        "bodyPreview": "Agenda attached.",
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "isAllDay": False,
        "isCancelled": False,
        "type": event_type,
        "seriesMasterId": series_master_id,
        "sensitivity": "normal",
        "showAs": "busy",
        "location": {"displayName": "Room 3"},
        "isOnlineMeeting": False,
        "organizer": {"emailAddress": {"name": "Ada Lovelace", "address": "ada@example.invalid"}},
        "isOrganizer": True,
        "responseStatus": {"response": "organizer", "time": "0001-01-01T00:00:00Z"},
        "attendees": [],
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


async def _list(
    client: GraphServiceClient,
    *,
    uri: str = _MASTER_URI,
    starts_on: date | datetime = _MARCH_MONDAY,
    ends_on: date | datetime = _MARCH_SUNDAY,
    time_zone: str = "UTC",
    limit: int = 25,
) -> lister.EventInstances:
    return await lister.list_event_instances(
        client, uri=uri, starts_on=starts_on, ends_on=ends_on, time_zone=time_zone, limit=limit
    )


@pytest.fixture
def master(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_MASTER).mock(
        return_value=httpx.Response(
            200, json=_event_payload(_MASTER_ID, event_type="seriesMaster", series_master_id=None)
        )
    )


@pytest.fixture
def instances(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_INSTANCES).mock(return_value=_page(_event_payload(_FIRST_ID)))


class TestTheQueryItComposes:
    @pytest.mark.usefixtures("master")
    async def test_both_bounds_are_the_instants_of_the_window_in_utc(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        _ = await _list(client, starts_on=_SUMMER_MONDAY, ends_on=_SUMMER_SUNDAY, time_zone=_ZURICH)

        params = instances.calls.last.request.url.params
        assert params["startDateTime"] == "2026-07-05T22:00:00+00:00"
        assert params["endDateTime"] == "2026-07-12T22:00:00+00:00"

    @pytest.mark.usefixtures("master")
    async def test_the_end_bound_opens_the_day_after_the_last_one_asked_for(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        _ = await _list(client, starts_on=_MARCH_MONDAY, ends_on=_MARCH_MONDAY)

        params = instances.calls.last.request.url.params
        assert params["startDateTime"] == "2026-03-02T00:00:00+00:00"
        assert params["endDateTime"] == "2026-03-03T00:00:00+00:00"

    @pytest.mark.usefixtures("master")
    async def test_a_moment_with_its_own_offset_keeps_the_instant_it_names(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        plus_two = timezone(timedelta(hours=2))

        _ = await _list(
            client,
            starts_on=datetime(2026, 3, 2, 13, 0, tzinfo=plus_two),
            ends_on=datetime(2026, 3, 2, 15, 30, tzinfo=plus_two),
            time_zone=_ZURICH,
        )

        params = instances.calls.last.request.url.params
        assert params["startDateTime"] == "2026-03-02T11:00:00+00:00"
        assert params["endDateTime"] == "2026-03-02T13:30:00+00:00"

    @pytest.mark.usefixtures("master")
    async def test_it_asks_for_the_shared_summary_fields_and_nothing_else(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        _ = await _list(client)

        assert instances.calls.last.request.url.params["$select"].split(",") == list(SUMMARY_FIELDS)

    @pytest.mark.usefixtures("master")
    async def test_it_sends_no_option_that_the_documentation_does_not_give_this_call(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        _ = await _list(client, limit=7)

        params = instances.calls.last.request.url.params
        assert sorted(params) == ["$select", "endDateTime", "startDateTime"]

    @pytest.mark.usefixtures("master")
    async def test_the_instances_are_asked_for_inside_the_calendar_the_handle_names(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        _ = await _list(client)

        sent, _query = instances.calls.last.request.url.raw_path.decode().split("?", 1)
        assert sent == f"/v1.0{_INSTANCES}"

    @pytest.mark.usefixtures("master")
    async def test_the_listing_asks_for_ids_that_outlive_the_event_being_filed(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        _ = await _list(client)

        assert 'IdType="ImmutableId"' in instances.calls.last.request.headers["Prefer"]

    @pytest.mark.usefixtures("master")
    async def test_the_preference_is_supplied_again_for_every_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        cursor = graph.get(_INSTANCES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_event_payload(_SECOND_ID))
        )
        graph.get(_INSTANCES).mock(
            return_value=_page(
                _event_payload(_FIRST_ID),
                next_link=f"{GRAPH_V1}{_INSTANCES}?$skiptoken=second",
            )
        )

        _ = await _list(client)

        assert 'IdType="ImmutableId"' in cursor.calls.last.request.headers["Prefer"]

    @pytest.mark.usefixtures("instances")
    async def test_the_series_is_read_before_its_instances_are_asked_for(
        self, client: GraphServiceClient, master: respx.Route
    ) -> None:
        _ = await _list(client)

        assert master.call_count == 1
        assert master.calls.last.request.url.params["$select"].split(",") == list(SUMMARY_FIELDS)

    @pytest.mark.usefixtures("master")
    async def test_no_request_asks_exchange_to_render_the_times(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        _ = await _list(client, time_zone=_ZURICH)

        assert "outlook.timezone" not in instances.calls.last.request.headers["Prefer"]


class TestWhatItAnswers:
    @pytest.mark.usefixtures("master")
    async def test_each_row_carries_the_handle_that_reads_the_event(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        instances.mock(return_value=_page(_event_payload(_FIRST_ID), _event_payload(_SECOND_ID)))

        answer = await _list(client)

        assert [row.uri for row in answer.events] == [
            EventHandle(_CALENDAR_ID, _FIRST_ID).uri,
            EventHandle(_CALENDAR_ID, _SECOND_ID).uri,
        ]

    @pytest.mark.usefixtures("master")
    async def test_each_row_points_back_to_the_series_master(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        instances.mock(return_value=_page(_event_payload(_FIRST_ID), _event_payload(_SECOND_ID)))

        answer = await _list(client)

        assert [row.series_master_uri for row in answer.events] == [_MASTER_URI, _MASTER_URI]

    @pytest.mark.usefixtures("master")
    async def test_an_occurrence_and_an_exception_are_told_apart_by_kind(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        instances.mock(
            return_value=_page(
                _event_payload(_FIRST_ID, event_type="occurrence"),
                _event_payload(_SECOND_ID, event_type="exception"),
            )
        )

        answer = await _list(client)

        assert [row.kind for row in answer.events] == ["occurrence", "exception"]
        assert all(row.in_series for row in answer.events)

    @pytest.mark.usefixtures("master", "instances")
    async def test_the_rows_are_converted_into_the_zone_that_was_asked_for(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _list(
            client, starts_on=_SUMMER_MONDAY, ends_on=_SUMMER_SUNDAY, time_zone=_ZURICH
        )

        row = answer.events[0]
        assert row.start is not None
        assert row.start.iso == "2026-03-02T14:00:00+01:00"
        assert row.start.local == "2026-03-02T13:00:00.0000000"
        assert row.start.time_zone == "UTC"

    @pytest.mark.usefixtures("master", "instances")
    async def test_the_window_that_was_asked_for_comes_back_with_the_rows(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _list(
            client, starts_on=_SUMMER_MONDAY, ends_on=_SUMMER_SUNDAY, time_zone=_ZURICH
        )

        assert answer.window.starts_at == "2026-07-06T00:00:00+02:00"
        assert answer.window.ends_at == "2026-07-13T00:00:00+02:00"
        assert answer.window.time_zone == _ZURICH

    @pytest.mark.usefixtures("master")
    async def test_the_order_graph_returned_is_the_order_answered(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        instances.mock(
            return_value=_page(
                _event_payload(_FIRST_ID, start="2026-03-04T11:00:00.0000000"),
                _event_payload(_SECOND_ID, start="2026-03-02T09:00:00.0000000"),
            )
        )

        answer = await _list(client)

        assert [row.start.iso for row in answer.events if row.start is not None] == [
            "2026-03-04T11:00:00+00:00",
            "2026-03-02T09:00:00+00:00",
        ]

    @pytest.mark.usefixtures("master")
    async def test_the_pages_of_a_window_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_INSTANCES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_event_payload(_SECOND_ID))
        )
        graph.get(_INSTANCES).mock(
            return_value=_page(
                _event_payload(_FIRST_ID),
                next_link=f"{GRAPH_V1}{_INSTANCES}?$skiptoken=second",
            )
        )

        answer = await _list(client)

        assert [row.uri for row in answer.events] == [
            EventHandle(_CALENDAR_ID, _FIRST_ID).uri,
            EventHandle(_CALENDAR_ID, _SECOND_ID).uri,
        ]
        assert answer.capped is False

    @pytest.mark.usefixtures("master")
    async def test_a_cap_that_left_more_of_the_window_on_offer_says_capped(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        instances.mock(return_value=_page(_event_payload(_FIRST_ID), _event_payload(_SECOND_ID)))

        answer = await _list(client, limit=1)

        assert [row.uri for row in answer.events] == [EventHandle(_CALENDAR_ID, _FIRST_ID).uri]
        assert answer.capped is True

    @pytest.mark.usefixtures("master")
    async def test_a_window_filled_exactly_by_its_own_end_is_not_capped(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        instances.mock(return_value=_page(_event_payload(_FIRST_ID), _event_payload(_SECOND_ID)))

        answer = await _list(client, limit=2)

        assert len(answer.events) == 2
        assert answer.capped is False

    @pytest.mark.usefixtures("master")
    async def test_a_window_with_no_date_of_the_series_answers_no_rows_and_no_cap(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        instances.mock(return_value=_page())

        answer = await _list(client)

        assert answer.events == []
        assert answer.capped is False


class TestWhatItRefuses:
    @pytest.mark.parametrize("event_type", ["occurrence", "exception"])
    async def test_one_date_of_a_series_is_refused_with_the_handle_of_the_master(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        instances: respx.Route,
        event_type: str,
    ) -> None:
        graph.get(_OCCURRENCE).mock(
            return_value=httpx.Response(200, json=_event_payload(_FIRST_ID, event_type=event_type))
        )

        with pytest.raises(ToolError, match="not the series master") as refused:
            _ = await _list(client, uri=EventHandle(_CALENDAR_ID, _FIRST_ID).uri)

        assert _MASTER_URI in str(refused.value)
        assert "series_master_uri" in str(refused.value)
        assert instances.call_count == 0

    async def test_an_event_that_does_not_repeat_is_sent_to_the_reader(
        self, client: GraphServiceClient, graph: respx.MockRouter, instances: respx.Route
    ) -> None:
        graph.get(_OCCURRENCE).mock(
            return_value=httpx.Response(
                200,
                json=_event_payload(_FIRST_ID, event_type="singleInstance", series_master_id=None),
            )
        )

        with pytest.raises(ToolError, match="not part of a recurring series") as refused:
            _ = await _list(client, uri=EventHandle(_CALENDAR_ID, _FIRST_ID).uri)

        assert "outlook_read_event" in str(refused.value)
        assert instances.call_count == 0

    @pytest.mark.parametrize(
        "uri",
        [
            "Weekly sync",
            _MASTER_ID,
            "outlook:///events/",
            CalendarHandle(_CALENDAR_ID).uri,
            MailMessageHandle(_FIRST_ID).uri,
        ],
    )
    async def test_a_uri_that_is_not_an_event_handle_never_reaches_graph(
        self, client: GraphServiceClient, master: respx.Route, uri: str
    ) -> None:
        with pytest.raises(ToolError, match="event handle"):
            _ = await _list(client, uri=uri)

        assert master.call_count == 0

    async def test_a_window_that_runs_backwards_never_reaches_graph(
        self, client: GraphServiceClient, master: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="backwards"):
            _ = await _list(client, starts_on=_MARCH_SUNDAY, ends_on=_MARCH_MONDAY)

        assert master.call_count == 0

    @pytest.mark.parametrize(
        "time_zone", ["W. Europe Standard Time", "Pacific Standard Time", "Zurich", "+02:00", ""]
    )
    async def test_a_zone_zoneinfo_cannot_resolve_never_reaches_graph(
        self, client: GraphServiceClient, master: respx.Route, time_zone: str
    ) -> None:
        with pytest.raises(ToolError, match="IANA"):
            _ = await _list(client, time_zone=time_zone)

        assert master.call_count == 0

    async def test_the_zone_refusal_warns_that_an_etc_gmt_key_reverses_its_sign(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="Etc/GMT") as refused:
            _ = await _list(client, time_zone="+02:00")

        assert "BEHIND UTC" in str(refused.value)

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_a_limit_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _list(client, limit=limit)


class TestTheSchemaItPublishes:
    async def test_the_series_and_the_window_are_what_a_caller_has_to_supply(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters.get("required", []) == ["uri", "starts_on", "ends_on"]
        assert tool.parameters["properties"]["time_zone"]["default"] == "UTC"

    async def test_the_floor_and_the_default_of_limit_are_published_and_no_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters["properties"]["limit"]["minimum"] == 1
        assert "maximum" not in tool.parameters["properties"]["limit"]
        assert tool.parameters["properties"]["limit"]["default"] == 25

    async def test_the_uri_argument_sends_the_caller_to_the_series_master_uri(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert "series_master_uri" in tool.parameters["properties"]["uri"]["description"]

    async def test_the_tool_only_reads(self, transport: httpx.AsyncClient) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True

    async def test_the_description_keeps_the_house_shape(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        described = tool.description or ""
        _lead, divider, notes = described.partition("\n\nNotes:\n")
        bullets = [line for line in notes.splitlines() if line.startswith("- ")]
        assert divider, "the lead paragraph is followed by a blank line and `Notes:`"
        assert 1 <= len(bullets) <= 4
        assert 45 <= len(described.split()) <= 210

    async def test_the_description_names_the_siblings_and_the_private_row_rule(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        described = tool.description or ""
        assert "outlook_list_events" in described
        assert "outlook_read_event" in described
        assert "`private`" in described
        assert "`confidential`" in described
        assert "`series_master_uri`" in described
        assert "refuses and gives the master handle" in described

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, object]", tool.output_schema)
        published = _fields(answer, lister.TOOL_NAME, root=answer)
        assert f"{lister.TOOL_NAME}.window.starts_at" in published
        assert f"{lister.TOOL_NAME}.events[].start.iso" in published
        undescribed = sorted(
            path
            for path, field in published.items()
            if not cast("Mapping[str, object]", field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"

    async def test_the_answer_publishes_the_window_the_rows_and_the_cap(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, object]", tool.output_schema)
        properties = cast("Mapping[str, object]", _resolved(answer, root=answer)["properties"])
        assert set(properties) == {"window", "events", "capped"}


class TestGraphFailures:
    async def test_a_refused_series_read_stops_before_the_instances_are_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter, instances: respx.Route
    ) -> None:
        graph.get(_MASTER).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _list(client)

        assert instances.call_count == 0

    @pytest.mark.usefixtures("master")
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, instances: respx.Route
    ) -> None:
        instances.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await _list(client)

    async def test_a_series_that_will_not_resolve_arrives_as_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_MASTER).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "gone"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _list(client)

    def test_the_permissions_are_the_ones_the_summary_fields_need(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Calendars.Read", "Calendars.Read.Shared")

    def test_a_series_that_will_not_resolve_is_answered_with_the_recovery_that_fits(self) -> None:
        assert "outlook_list_events" in lister.GRAPH_NOT_FOUND
        assert "series_master_uri" in lister.GRAPH_NOT_FOUND
