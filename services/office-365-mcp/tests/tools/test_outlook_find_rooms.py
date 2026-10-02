import re
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, GraphForbidden, GraphNotFound
from office_365_mcp.server.manifest import NEEDS_ADMIN_CONSENT
from office_365_mcp.shared.seam import READ_ONLY, REQUESTABLE_PERMISSIONS
from office_365_mcp.tools import outlook_find_rooms as finder

from .conftest import GRAPH_V1

_ROOMS_PATH = "/places/graph.room"

_ROOM_LIST = "bldg2@example.invalid"

_ROOM_LIST_PATH = "/places/bldg2%40example.invalid/graph.roomList/rooms"

_RETRY = "If you call this tool again with the same arguments, the call will fail the same way."


def _room(
    *,
    name: str | None = "Conf Room 100",
    address: str | None = "cf100@example.invalid",
    capacity: int | None = 50,
    booking_type: str | None = "standard",
) -> dict[str, object]:
    return {
        "id": "3162F1E1-C4C0-604B-51D8-91DA78989EB1",
        "emailAddress": address,
        "displayName": name,
        "address": {"street": "4567 Main Street", "city": "Buffalo", "countryOrRegion": "USA"},
        "phone": "000-000-0000",
        "nickname": "Conf Room",
        "label": "100",
        "capacity": capacity,
        "building": "1",
        "floorNumber": 1,
        "floorLabel": "P",
        "isWheelChairAccessible": False,
        "bookingType": booking_type,
        "tags": ["bean bags"],
        "audioDeviceName": None,
        "videoDeviceName": "camera",
        "displayDeviceName": "surface hub",
        "teamsEnabledState": "enabled",
        "placeId": "080ed1a0-7b54-4995-85a5-eeec751786f5",
    }


def _page(*rooms: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(rooms)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _undescribed(schema: Mapping[str, object]) -> list[str]:
    definitions = cast("Mapping[str, Mapping[str, object]]", schema.get("$defs", {}))
    return sorted(
        f"{owner}.{name}"
        for owner, node in {"answer": schema, **definitions}.items()
        for name, field in cast(
            "Mapping[str, Mapping[str, object]]", node.get("properties", {})
        ).items()
        if not field.get("description")
    )


def _server(transport: httpx.AsyncClient) -> FastMCP:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    finder.register(mcp, transport)
    return mcp


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    tool = await _server(transport).get_tool(finder.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


@pytest.fixture
def rooms(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_ROOMS_PATH)


@pytest.fixture
def listed_rooms(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_ROOM_LIST_PATH)


class TestTheRequestItMakes:
    async def test_it_reads_every_room_of_the_organization_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter, rooms: respx.Route
    ) -> None:
        rooms.mock(return_value=_page(_room()))

        _ = await finder.find_rooms(client, limit=50)

        assert rooms.call_count == 1
        assert len(graph.calls) == 1
        assert rooms.calls.last.request.url.path == "/v1.0/places/graph.room"

    async def test_a_room_list_reads_the_rooms_of_that_list_by_its_address(
        self, client: GraphServiceClient, graph: respx.MockRouter, listed_rooms: respx.Route
    ) -> None:
        listed_rooms.mock(return_value=_page(_room()))

        _ = await finder.find_rooms(client, room_list=_ROOM_LIST, limit=50)

        assert listed_rooms.call_count == 1
        assert len(graph.calls) == 1

    async def test_a_room_list_with_spaces_around_it_reaches_graph_trimmed(
        self, client: GraphServiceClient, graph: respx.MockRouter, listed_rooms: respx.Route
    ) -> None:
        listed_rooms.mock(return_value=_page(_room()))

        _ = await finder.find_rooms(client, room_list=f"  {_ROOM_LIST} ", limit=50)

        assert listed_rooms.call_count == 1
        assert len(graph.calls) == 1
        assert (
            listed_rooms.calls.last.request.url.path
            == f"/v1.0/places/{_ROOM_LIST}/graph.roomList/rooms"
        )

    async def test_it_sends_no_query_option(
        self, client: GraphServiceClient, rooms: respx.Route
    ) -> None:
        rooms.mock(return_value=_page(_room()))

        _ = await finder.find_rooms(client, min_capacity=8, limit=5)

        assert dict(rooms.calls.last.request.url.params) == {}


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            "Building 2",
            "bldg2",
            "a@b@c",
            "bldg2@example.invalid x",
            " bldg2@exam ple.invalid ",
            "   ",
        ],
    )
    async def test_a_room_list_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="one SMTP address in `room_list`") as raised:
            _ = await finder.find_rooms(client, room_list=value, limit=50)

        assert "This tool read nothing." in str(raised.value)
        assert _RETRY in str(raised.value)
        assert len(graph.calls) == 0

    async def test_a_limit_above_the_scan_cap_fails_validation_before_it_reaches_graph(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        async with Client(FastMCPTransport(_server(transport))) as caller:
            with pytest.raises(ToolError, match=f"less than or equal to {MAX_SCANNED_ITEMS}"):
                _ = await caller.call_tool(finder.TOOL_NAME, {"limit": MAX_SCANNED_ITEMS + 1})

        assert len(graph.calls) == 0


class TestWhatItAnswers:
    async def test_a_row_carries_the_address_to_book_and_what_the_room_offers(
        self, client: GraphServiceClient, rooms: respx.Route
    ) -> None:
        rooms.mock(return_value=_page(_room()))

        row = (await finder.find_rooms(client, limit=50)).rooms[0]

        assert row.display_name == "Conf Room 100"
        assert row.address == "cf100@example.invalid"
        assert row.capacity == 50
        assert row.building == "1"
        assert row.floor_number == 1
        assert row.floor_label == "P"
        assert row.label == "100"
        assert row.nickname == "Conf Room"
        assert row.is_wheel_chair_accessible is False
        assert row.tags == ["bean bags"]
        assert row.audio_device_name is None
        assert row.video_device_name == "camera"
        assert row.display_device_name == "surface hub"

    async def test_the_enum_values_read_as_their_wire_values(
        self, client: GraphServiceClient, rooms: respx.Route
    ) -> None:
        rooms.mock(return_value=_page(_room(booking_type="reserved")))

        row = (await finder.find_rooms(client, limit=50)).rooms[0]

        assert row.booking_type == "reserved"
        assert row.teams_enabled_state == "enabled"

    async def test_a_row_with_nothing_but_an_id_answers_nulls(
        self, client: GraphServiceClient, rooms: respx.Route
    ) -> None:
        rooms.mock(return_value=_page({"id": "3162F1E1-C4C0-604B-51D8-91DA78970B97"}))

        row = (await finder.find_rooms(client, limit=50)).rooms[0]

        assert row.display_name is None
        assert row.address is None
        assert row.capacity is None
        assert row.booking_type is None
        assert row.teams_enabled_state is None
        assert row.tags == []

    async def test_min_capacity_keeps_only_the_rooms_that_hold_that_many(
        self, client: GraphServiceClient, rooms: respx.Route
    ) -> None:
        rooms.mock(
            return_value=_page(
                _room(name="Small", capacity=4),
                _room(name="Exact", capacity=8),
                _room(name="Large", capacity=40),
                _room(name="Unknown", capacity=None),
            )
        )

        listed = await finder.find_rooms(client, min_capacity=8, limit=50)

        assert [row.display_name for row in listed.rooms] == ["Exact", "Large"]
        assert listed.capped is False

    async def test_without_min_capacity_a_room_with_no_capacity_is_listed(
        self, client: GraphServiceClient, rooms: respx.Route
    ) -> None:
        rooms.mock(return_value=_page(_room(name="Unknown", capacity=None)))

        listed = await finder.find_rooms(client, limit=50)

        assert [row.display_name for row in listed.rooms] == ["Unknown"]

    async def test_the_pages_of_the_listing_are_followed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_ROOMS_PATH, params={"$skiptoken": "second"}).mock(
            return_value=_page(_room(name="Conf Room 200"))
        )
        graph.get(_ROOMS_PATH).mock(
            return_value=_page(_room(), next_link=f"{GRAPH_V1}{_ROOMS_PATH}?$skiptoken=second")
        )

        listed = await finder.find_rooms(client, limit=50)

        assert [row.display_name for row in listed.rooms] == ["Conf Room 100", "Conf Room 200"]
        assert listed.capped is False

    async def test_a_limit_that_left_more_rooms_on_offer_says_capped(
        self, client: GraphServiceClient, rooms: respx.Route
    ) -> None:
        rooms.mock(return_value=_page(_room(), _room(name="Conf Room 200")))

        listed = await finder.find_rooms(client, limit=1)

        assert [row.display_name for row in listed.rooms] == ["Conf Room 100"]
        assert listed.capped is True

    async def test_an_organization_with_no_listed_room_answers_an_empty_listing(
        self, client: GraphServiceClient, rooms: respx.Route
    ) -> None:
        rooms.mock(return_value=_page())

        listed = await finder.find_rooms(client, limit=50)

        assert listed.rooms == []
        assert listed.capped is False


class TestGraphFailures:
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, rooms: respx.Route
    ) -> None:
        rooms.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await finder.find_rooms(client, limit=50)

    async def test_a_room_list_graph_does_not_find_is_a_not_found(
        self, client: GraphServiceClient, listed_rooms: respx.Route
    ) -> None:
        listed_rooms.mock(return_value=httpx.Response(404))

        with pytest.raises(GraphNotFound):
            _ = await finder.find_rooms(client, room_list=_ROOM_LIST, limit=50)

    def test_the_not_found_advice_points_at_the_room_list(self) -> None:
        assert "this tool listed no room" in finder.GRAPH_NOT_FOUND
        assert "call this tool again without `room_list`" in finder.GRAPH_NOT_FOUND
        assert _RETRY in finder.GRAPH_NOT_FOUND


class TestHowItDeclaresItself:
    def test_the_permission_is_the_least_privileged_one_microsoft_names(self) -> None:
        assert finder.GRAPH_PERMISSIONS == ("Place.Read.All",)

    def test_the_permission_is_requestable_and_needs_an_administrator(self) -> None:
        assert "Place.Read.All" in REQUESTABLE_PERMISSIONS
        assert NEEDS_ADMIN_CONSENT["Place.Read.All"] is True

    def test_the_call_that_proves_the_permissions_takes_no_arguments(self) -> None:
        assert finder.GRAPH_CALL_EXAMPLE == {}

    async def test_every_argument_is_optional_and_bounded(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        assert set(properties) == {"room_list", "min_capacity", "limit"}
        assert parameters.get("required", []) == []
        assert properties["limit"]["default"] == 50
        assert properties["limit"]["minimum"] == 1
        assert properties["limit"]["maximum"] == MAX_SCANNED_ITEMS

    async def test_the_input_schema_is_a_plain_object_at_its_root(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert parameters["type"] == "object"
        assert not {"anyOf", "oneOf", "allOf", "not", "enum", "const"} & set(parameters)

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_says_it_only_reads(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is READ_ONLY["readOnlyHint"]

    async def test_the_description_is_a_lead_and_a_few_notes_of_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        assert separator, "the description has no Notes section"
        assert lead.strip() != ""
        assert 1 <= len([line for line in notes.splitlines() if line.startswith("- ")]) <= 4
        assert 45 <= len(description.split()) <= 210
        sentences = re.split(r"(?<=[.?])\s+", description)
        assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_the_description_names_the_sibling_tools_and_the_places_setting(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "outlook_create_event books a room" in description
        assert "outlook_check_availability shows whether a room is free" in description
        assert "Do not book a room that the user did not choose." in description
        assert "after an administrator turns on buildings in the Places settings" in description
        assert "An empty list does not prove that the organization has no room." in description

    async def test_a_row_says_which_tools_take_its_address(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast(
            "Mapping[str, Mapping[str, Mapping[str, Mapping[str, Mapping[str, str]]]]]",
            tool.output_schema,
        )
        described = answer["$defs"]["RoomSummary"]["properties"]["address"]["description"]
        assert "Pass it in `room_addresses` to outlook_create_event" in described
        assert "in `addresses` to outlook_check_availability" in described

    async def test_the_arguments_say_where_the_filtering_happens(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, str]]", parameters["properties"])
        assert "only by its address, not by its name" in properties["room_list"]["description"]
        assert (
            "removes the smaller rooms after Microsoft 365 returns the list"
            in (properties["min_capacity"]["description"])
        )
        assert "each room with no capacity" in properties["min_capacity"]["description"]

    async def test_the_limit_and_capped_say_what_the_scan_cap_does(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, str]]", parameters["properties"])
        limit = properties["limit"]["description"]
        assert f"How many rooms to return, at most {MAX_SCANNED_ITEMS}." in limit
        assert "Read `capped` before you raise `limit`." in limit
        assert "Raise `limit` to see more." not in limit
        answer = cast("Mapping[str, Mapping[str, Mapping[str, str]]]", tool.output_schema)
        capped = answer["properties"]["capped"]["description"]
        assert "True when the listing stopped early, so more rooms can remain." in capped
        assert (
            "The listing stops after `limit` rooms that match, or after it reads "
            + f"{MAX_SCANNED_ITEMS} rooms."
        ) in capped
        assert (
            "If the answer holds fewer than `limit` rooms, a higher `limit` cannot help." in capped
        )
        assert "Then name a `room_list`." in capped
        assert "raise `limit` or name" not in capped
        assert 15 <= len(limit.split()) <= 60
        assert 15 <= len(capped.split()) <= 60

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        assert _undescribed(answer) == []
