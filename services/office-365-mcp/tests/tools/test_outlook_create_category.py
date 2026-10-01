import json
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.tools import FunctionTool, Tool
from msgraph.generated.models.category_color import CategoryColor
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphFailure, GraphForbidden
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import outlook_create_category as creator

_CATEGORIES_PATH = "/me/outlook/masterCategories"

_ALL_COLORS: tuple[str, ...] = tuple(str.__str__(color) for color in CategoryColor)


def _category_payload(
    *, name: str | None = "Follow up", color: str | None = "preset0"
) -> dict[str, object]:
    return {"id": "bac262b7-485d-4739-b436-e31467d64fac", "displayName": name, "color": color}


@pytest.fixture
def categories(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_CATEGORIES_PATH)


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _property(parameters: Mapping[str, object], name: str) -> Mapping[str, object]:
    properties = cast("Mapping[str, object]", parameters["properties"])
    return cast("Mapping[str, object]", properties[name])


class TestWhatItSendsToGraph:
    async def test_it_posts_a_display_name_and_a_color_and_nothing_else(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=httpx.Response(201, json=_category_payload()))

        _ = await creator.create_category(client, name="Follow up", color="preset9")

        assert categories.call_count == 1
        assert _sent(categories) == {"displayName": "Follow up", "color": "preset9"}

    @pytest.mark.parametrize("color", _ALL_COLORS)
    async def test_every_color_the_schema_offers_reaches_graph_as_its_wire_value(
        self, client: GraphServiceClient, categories: respx.Route, color: str
    ) -> None:
        categories.mock(return_value=httpx.Response(201, json=_category_payload(color=color)))

        _ = await creator.create_category(
            client, name="Follow up", color=cast("creator.CategoryColorName", color)
        )

        assert _sent(categories)["color"] == color

    async def test_the_content_type_is_json(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=httpx.Response(201, json=_category_payload()))

        _ = await creator.create_category(client, name="Follow up", color="none")

        assert categories.calls.last.request.headers["content-type"] == "application/json"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=httpx.Response(503))

        with pytest.raises(GraphFailure):
            _ = await creator.create_category(client, name="Follow up", color="none")

        assert categories.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItAnswers:
    async def test_the_answer_is_the_name_and_color_graph_stored(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(
            return_value=httpx.Response(201, json=_category_payload(name="Stored", color="preset4"))
        )

        answer = await creator.create_category(client, name="Asked", color="preset9")

        assert answer.name == "Stored"
        assert answer.color == "preset4"

    async def test_the_color_reads_as_its_wire_value_and_not_the_enum_members_own_repr(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=httpx.Response(201, json=_category_payload(color="preset3")))

        answer = await creator.create_category(client, name="Follow up", color="preset3")

        assert answer.color == "preset3"

    async def test_the_explicit_none_color_is_the_literal_string_not_a_null(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=httpx.Response(201, json=_category_payload(color="none")))

        answer = await creator.create_category(client, name="Follow up", color="none")

        assert answer.color == "none"

    async def test_a_category_graph_named_no_color_for_answers_a_null_color(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=httpx.Response(201, json=_category_payload(color=None)))

        answer = await creator.create_category(client, name="Follow up", color="none")

        assert answer.color is None

    async def test_a_create_that_names_no_display_name_is_a_programming_error(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=httpx.Response(201, json=_category_payload(name=None)))

        with pytest.raises(AssertionError):
            _ = await creator.create_category(client, name="Follow up", color="none")


class TestGraphFailures:
    async def test_a_403_is_a_forbidden(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await creator.create_category(client, name="Follow up", color="none")

    async def test_a_409_is_a_graph_failure_that_keeps_its_status(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(
            return_value=httpx.Response(
                409, json={"error": {"code": "ErrorItemExists", "message": "already exists"}}
            )
        )

        with pytest.raises(GraphFailure) as failure:
            _ = await creator.create_category(client, name="Follow up", color="none")

        assert failure.value.status == 409

    async def test_the_call_example_reaches_graph(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=httpx.Response(201, json=_category_payload()))
        example = cast("dict[str, str]", creator.GRAPH_CALL_EXAMPLE)

        _ = await creator.create_category(client, name=example["name"], color="none")

        assert categories.call_count == 1


class TestHowItDeclaresItself:
    def test_the_permission_is_mailbox_settings_read_write(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("MailboxSettings.ReadWrite",)

    def test_the_change_is_shown_by_the_category_listing(self) -> None:
        assert creator.CHANGE_SHOWN_BY == ("outlook_list_categories",)

    def test_the_call_example_is_a_name(self) -> None:
        assert set(creator.GRAPH_CALL_EXAMPLE) == {"name"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(creator.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_a_name_and_a_color_and_no_mailbox(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"name", "color"}

    async def test_only_the_name_is_required(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        assert parameters["required"] == ["name"]

    async def test_the_name_cannot_be_empty(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        assert _property(parameters, "name")["minLength"] == 1

    async def test_the_color_defaults_to_none(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        assert _property(parameters, "color")["default"] == "none"

    async def test_the_color_offers_every_color_microsoft_defines_and_no_other(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        reference = cast("str", _property(parameters, "color")["$ref"])
        definitions = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
        offered = cast("list[str]", definitions[reference.removeprefix("#/$defs/")]["enum"])
        assert sorted(offered) == sorted(_ALL_COLORS)

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_an_additive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)
        assert isinstance(tool, FunctionTool)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

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

    async def test_the_description_says_it_never_asks_to_agree(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "never asks anybody to agree" in description
        assert "own mailbox" in description

    async def test_the_description_names_the_tools_that_list_and_apply_the_category(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "outlook_mark_mail puts a category on a message" in description
        assert (
            "make sure that outlook_list_categories does not show a category named `name`"
            in description
        )

    async def test_the_description_states_the_duplicate_name_failure_as_a_fact(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "Microsoft refuses a duplicate name, and the same name fails again" in description
        assert "confirmed on a test tenant" not in description
        assert "bad request" not in description

    async def test_the_name_says_it_must_be_unique_and_cannot_change(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        described = cast("str", _property(parameters, "name")["description"])
        assert "must be unique in the user's list of categories" in described
        assert "cannot change after this call" in described

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        properties = cast("Mapping[str, Mapping[str, object]]", answer["properties"])
        assert set(properties) == {"name", "color"}
        undescribed = sorted(
            name for name, field in properties.items() if not field.get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"
