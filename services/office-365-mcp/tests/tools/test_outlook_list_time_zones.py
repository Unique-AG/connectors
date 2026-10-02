import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.calendar import ZONE_NAME, zone_named
from office_365_mcp.tools import PRESETS, TOOL_NAMES
from office_365_mcp.tools import outlook_list_time_zones as lister

from .conftest import GRAPH_V1

_WINDOWS_PATH = "/me/outlook/supportedTimeZones()"
_IANA_PATH = (
    "/me/outlook/supportedTimeZones(TimeZoneStandard=microsoft.graph.timeZoneStandard'Iana')"
)


def _zone_payload(
    *, alias: str | None = "Aleutian Standard Time", display_name: str | None = "Aleutian Islands"
) -> dict[str, object]:
    return {"alias": alias, "displayName": display_name}


def _page(*zones: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(zones)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


@pytest.fixture
def zones(graph: respx.MockRouter) -> respx.Route:
    return graph.get(url__startswith=f"{GRAPH_V1}/me/outlook/supportedTimeZones")


def _unguarded(tool: Tool) -> list[str]:
    schemas = json.dumps([tool.parameters, tool.output_schema], ensure_ascii=False)
    prose = [tool.description or "", *re.findall(r'"description": "((?:[^"\\]|\\.)*)"', schemas)]
    held = frozenset(TOOL_NAMES).intersection(
        *(names for names in PRESETS.values() if tool.name in names)
    )
    mention = re.compile(rf"\b(?:{'|'.join(TOOL_NAMES)})\b")
    offenders: list[str] = []
    for sentence in (s for text in prose for s in re.split(r"\n\s*-\s+|(?<=[.!?])\s+", text)):
        outside = set(mention.findall(sentence)) - held
        guard = sentence.split(",", 1)[0]
        if outside and not (
            guard.startswith("If this deployment exposes ")
            and outside <= set(mention.findall(guard))
        ):
            offenders.append(sentence)
    return offenders


class TestTheRequestItSends:
    async def test_the_windows_standard_calls_the_function_the_sdk_spells(
        self, client: GraphServiceClient, zones: respx.Route
    ) -> None:
        zones.mock(return_value=_page(_zone_payload()))

        _ = await lister.list_time_zones(client, standard="windows")

        assert zones.calls.last.request.url.raw_path.decode() == f"/v1.0{_WINDOWS_PATH}"

    async def test_no_standard_is_the_windows_standard(
        self, client: GraphServiceClient, zones: respx.Route
    ) -> None:
        zones.mock(return_value=_page(_zone_payload()))

        _ = await lister.list_time_zones(client)

        assert zones.calls.last.request.url.raw_path.decode() == f"/v1.0{_WINDOWS_PATH}"

    async def test_the_iana_standard_calls_the_function_the_way_microsoft_documents_it(
        self, client: GraphServiceClient, zones: respx.Route
    ) -> None:
        zones.mock(return_value=_page(_zone_payload(alias="US/Aleutian")))

        _ = await lister.list_time_zones(client, standard="iana")

        assert zones.calls.last.request.url.raw_path.decode() == f"/v1.0{_IANA_PATH}"

    @pytest.mark.parametrize("standard", ["windows", "iana"])
    async def test_neither_standard_sends_a_query_or_asks_for_anything_but_json(
        self, client: GraphServiceClient, zones: respx.Route, standard: lister.Standard
    ) -> None:
        zones.mock(return_value=_page(_zone_payload()))

        _ = await lister.list_time_zones(client, standard=standard)

        sent = zones.calls.last.request
        assert sent.url.query == b""
        assert sent.headers["accept"] == "application/json"

    @pytest.mark.parametrize("standard", ["windows", "iana"])
    async def test_the_read_happens_exactly_once(
        self, client: GraphServiceClient, zones: respx.Route, standard: lister.Standard
    ) -> None:
        zones.mock(return_value=_page(_zone_payload()))

        _ = await lister.list_time_zones(client, standard=standard)

        assert zones.call_count == 1


class TestWhatItAnswers:
    async def test_it_maps_each_row_to_its_alias_and_display_name(
        self, client: GraphServiceClient, zones: respx.Route
    ) -> None:
        zones.mock(
            return_value=_page(
                _zone_payload(alias="Aleutian Standard Time", display_name="Aleutian Islands"),
                _zone_payload(alias="UTC-11", display_name="Coordinated Universal Time-11"),
            )
        )

        listed = await lister.list_time_zones(client)

        assert [(zone.alias, zone.display_name) for zone in listed.time_zones] == [
            ("Aleutian Standard Time", "Aleutian Islands"),
            ("UTC-11", "Coordinated Universal Time-11"),
        ]
        assert listed.capped is False

    async def test_an_iana_row_answers_the_same_shape(
        self, client: GraphServiceClient, zones: respx.Route
    ) -> None:
        zones.mock(
            return_value=_page(_zone_payload(alias="US/Aleutian", display_name="US/Aleutian"))
        )

        listed = await lister.list_time_zones(client, standard="iana")

        assert [(zone.alias, zone.display_name) for zone in listed.time_zones] == [
            ("US/Aleutian", "US/Aleutian")
        ]

    async def test_a_row_with_no_display_name_answers_a_null(
        self, client: GraphServiceClient, zones: respx.Route
    ) -> None:
        zones.mock(return_value=_page(_zone_payload(display_name=None)))

        listed = await lister.list_time_zones(client)

        assert listed.time_zones[0].display_name is None

    async def test_an_empty_listing_answers_zero_rows(
        self, client: GraphServiceClient, zones: respx.Route
    ) -> None:
        zones.mock(return_value=_page())

        listed = await lister.list_time_zones(client)

        assert listed.time_zones == []
        assert listed.capped is False, "an empty listing is the whole of it, not a cap"

    async def test_the_pages_of_the_listing_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_WINDOWS_PATH, params={"$skiptoken": "second"}).mock(
            return_value=_page(_zone_payload(alias="UTC-11"))
        )
        graph.get(_WINDOWS_PATH).mock(
            return_value=_page(
                _zone_payload(alias="Aleutian Standard Time"),
                next_link=f"{GRAPH_V1}{_WINDOWS_PATH}?$skiptoken=second",
            )
        )

        listed = await lister.list_time_zones(client)

        assert [zone.alias for zone in listed.time_zones] == ["Aleutian Standard Time", "UTC-11"]
        assert listed.capped is False, "the walk reached the end of the listing"

    async def test_a_scan_limit_that_left_more_zones_on_offer_says_capped(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 1)
        graph.get(_WINDOWS_PATH, params={"$skiptoken": "second"}).mock(
            return_value=_page(_zone_payload(alias="UTC-11"))
        )
        graph.get(_WINDOWS_PATH).mock(
            return_value=_page(
                _zone_payload(alias="Aleutian Standard Time"),
                next_link=f"{GRAPH_V1}{_WINDOWS_PATH}?$skiptoken=second",
            )
        )

        listed = await lister.list_time_zones(client)

        assert [zone.alias for zone in listed.time_zones] == ["Aleutian Standard Time"]
        assert listed.capped is True


class TestTheSchemaItPublishes:
    async def test_it_publishes_one_optional_argument_with_two_values(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        assert list(properties) == ["standard"]
        assert properties["standard"]["default"] == "windows"
        definitions = cast("Mapping[str, Mapping[str, object]]", tool.parameters["$defs"])
        assert definitions["Standard"]["enum"] == ["windows", "iana"]
        assert tool.parameters.get("required", []) == []

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, object]", tool.output_schema)
        nodes = [answer, *cast("Mapping[str, Mapping[str, object]]", answer["$defs"]).values()]
        published = {
            name: field
            for node in nodes
            for name, field in cast("Mapping[str, object]", node["properties"]).items()
        }
        assert {"time_zones", "capped", "alias", "display_name"} <= set(published)
        undescribed = sorted(
            name
            for name, field in published.items()
            if not cast("Mapping[str, object]", field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"

    async def test_every_other_tool_it_names_comes_after_a_guard_that_names_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert _unguarded(tool) == []

    async def test_the_description_says_which_tools_take_only_iana_names(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        description = " ".join((tool.description or "").split())
        assert (
            "A tool that lists or reads events, event occurrences, or reminders takes only IANA "
            "names in `time_zone`."
        ) in description
        assert "This tool lists Windows names by default." in description
        assert "For a tool that takes only IANA names, set `standard` to `iana`." in description

    async def test_the_description_says_a_writing_tool_sends_the_name_as_written_and_can_be_refused(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        description = " ".join((tool.description or "").split())
        assert (
            "If this deployment exposes outlook_check_availability, that tool also takes only "
            "IANA names."
        ) in description
        assert (
            "A tool that creates or changes an event sends the zone name to Microsoft as written."
        ) in description
        assert "Microsoft documents that it can refuse some zone names there." in description
        assert "Microsoft accepts either spelling" not in description
        assert "Every other tool that takes a zone name" not in description

    def test_the_call_that_proves_the_permissions_takes_no_arguments(self) -> None:
        assert lister.GRAPH_CALL_EXAMPLE == {}


class TestTheDescriptionAgainstTheTools:
    @pytest.mark.parametrize(
        "alias", ["Aleutian Standard Time", "UTC-11", "US/Aleutian", "Etc/GMT+12"]
    )
    def test_the_event_writers_accept_every_alias_graph_documents(self, alias: str) -> None:
        assert re.fullmatch(ZONE_NAME, alias)

    def test_the_event_readers_resolve_an_iana_alias_and_not_a_windows_one(self) -> None:
        assert zone_named("US/Aleutian") is not None
        assert zone_named("Aleutian Standard Time") is None

    def test_an_etc_gmt_plus_name_is_behind_utc(self) -> None:
        zone = zone_named("Etc/GMT+12")

        assert zone is not None
        assert datetime(2026, 1, 1, tzinfo=zone).utcoffset() == timedelta(hours=-12)


class TestGraphFailures:
    @pytest.mark.parametrize("standard", ["windows", "iana"])
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, zones: respx.Route, standard: lister.Standard
    ) -> None:
        zones.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_time_zones(client, standard=standard)

    def test_the_permissions_are_the_ones_microsoft_documents(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("User.Read",)
