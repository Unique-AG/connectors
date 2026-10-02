import json
import re
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.tools import PRESETS, TOOL_NAMES
from office_365_mcp.tools import outlook_list_focused_overrides as lister

from .conftest import GRAPH_V1

_OVERRIDES = "/me/inferenceClassification/overrides"


def _override_payload(
    *,
    address: str | None = "grace@example.invalid",
    name: str | None = "Grace Hopper",
    classify_as: str | None = "focused",
) -> dict[str, object]:
    sender: dict[str, object] = {}
    if address is not None:
        sender["address"] = address
    if name is not None:
        sender["name"] = name
    return {
        "id": "98f5bdef-576a-404d-a2ea-07a3cf11a9b9",
        "classifyAs": classify_as,
        "senderEmailAddress": sender,
    }


def _page(*overrides: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(overrides)}
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


@pytest.fixture
def overrides(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_OVERRIDES)


class TestTheRequestItMakes:
    async def test_it_reads_the_overrides_of_the_signed_in_user(
        self, client: GraphServiceClient, overrides: respx.Route
    ) -> None:
        overrides.mock(return_value=_page(_override_payload()))

        _ = await lister.list_focused_overrides(client)

        assert overrides.call_count == 1
        assert overrides.calls.last.request.url.path == f"/v1.0{_OVERRIDES}"

    async def test_it_sends_no_query_option_because_the_page_documents_none(
        self, client: GraphServiceClient, overrides: respx.Route
    ) -> None:
        overrides.mock(return_value=_page(_override_payload()))

        _ = await lister.list_focused_overrides(client)

        assert dict(overrides.calls.last.request.url.params) == {}


class TestWhatItAnswers:
    async def test_a_row_carries_the_address_the_name_and_the_tab(
        self, client: GraphServiceClient, overrides: respx.Route
    ) -> None:
        overrides.mock(
            return_value=_page(
                _override_payload(
                    address="randi@example.invalid", name="Randi Welch", classify_as="other"
                )
            )
        )

        row = (await lister.list_focused_overrides(client)).overrides[0]

        assert row.sender_address == "randi@example.invalid"
        assert row.sender_name == "Randi Welch"
        assert row.classify_as == "other"

    async def test_the_focused_tab_reads_as_its_wire_value(
        self, client: GraphServiceClient, overrides: respx.Route
    ) -> None:
        overrides.mock(return_value=_page(_override_payload(classify_as="focused")))

        row = (await lister.list_focused_overrides(client)).overrides[0]

        assert row.classify_as == "focused"

    async def test_a_sender_with_no_stored_name_answers_a_null_name(
        self, client: GraphServiceClient, overrides: respx.Route
    ) -> None:
        overrides.mock(return_value=_page(_override_payload(name=None)))

        row = (await lister.list_focused_overrides(client)).overrides[0]

        assert row.sender_name is None
        assert row.sender_address == "grace@example.invalid"

    async def test_a_tab_that_graph_spells_in_a_way_unknown_here_answers_null(
        self, client: GraphServiceClient, overrides: respx.Route
    ) -> None:
        overrides.mock(return_value=_page(_override_payload(classify_as="somethingNew")))

        row = (await lister.list_focused_overrides(client)).overrides[0]

        assert row.classify_as is None

    async def test_the_rows_keep_the_order_graph_returned_them_in(
        self, client: GraphServiceClient, overrides: respx.Route
    ) -> None:
        overrides.mock(
            return_value=_page(
                _override_payload(address="b@example.invalid"),
                _override_payload(address="a@example.invalid"),
            )
        )

        listed = await lister.list_focused_overrides(client)

        assert [row.sender_address for row in listed.overrides] == [
            "b@example.invalid",
            "a@example.invalid",
        ]

    async def test_the_pages_of_the_listing_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_OVERRIDES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_override_payload(address="second@example.invalid"))
        )
        graph.get(_OVERRIDES).mock(
            return_value=_page(
                _override_payload(address="first@example.invalid"),
                next_link=f"{GRAPH_V1}{_OVERRIDES}?$skiptoken=second",
            )
        )

        listed = await lister.list_focused_overrides(client)

        assert [row.sender_address for row in listed.overrides] == [
            "first@example.invalid",
            "second@example.invalid",
        ]
        assert listed.capped is False, "the walk reached the end of the listing"

    async def test_a_scan_limit_that_left_more_senders_on_offer_says_capped(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 1)
        graph.get(_OVERRIDES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_override_payload(address="second@example.invalid"))
        )
        graph.get(_OVERRIDES).mock(
            return_value=_page(
                _override_payload(address="first@example.invalid"),
                next_link=f"{GRAPH_V1}{_OVERRIDES}?$skiptoken=second",
            )
        )

        listed = await lister.list_focused_overrides(client)

        assert [row.sender_address for row in listed.overrides] == ["first@example.invalid"]
        assert listed.capped is True

    async def test_a_mailbox_with_no_overrides_answers_an_empty_listing(
        self, client: GraphServiceClient, overrides: respx.Route
    ) -> None:
        overrides.mock(return_value=_page())

        listed = await lister.list_focused_overrides(client)

        assert listed.overrides == []
        assert listed.capped is False, "an empty listing is the whole of it, not a cap"


class TestTheSchemaItPublishes:
    async def test_it_publishes_no_arguments_at_all(self, transport: httpx.AsyncClient) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters.get("properties", {}) == {}
        assert tool.parameters.get("required", []) == []

    async def test_it_says_it_only_reads(self, transport: httpx.AsyncClient) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True

    async def test_the_description_names_the_tool_that_changes_a_row(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.description is not None
        assert (
            "If this deployment exposes outlook_set_focused_override, that tool adds a sender or "
            "changes a row"
        ) in tool.description
        assert "every future message from a listed sender" in tool.description

    async def test_the_description_is_a_lead_and_a_few_notes_of_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        assert separator, "the description has no Notes section"
        assert lead.strip() != ""
        assert 1 <= len([line for line in notes.splitlines() if line.startswith("- ")]) <= 4
        assert 45 <= len(description.split()) <= 210
        sentences = re.split(r"(?<=[.?])\s+", description)
        assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_a_row_says_which_value_goes_to_the_tool_that_changes_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast(
            "Mapping[str, Mapping[str, Mapping[str, Mapping[str, Mapping[str, str]]]]]",
            tool.output_schema,
        )
        described = answer["$defs"]["FocusedOverride"]["properties"]["sender_address"][
            "description"
        ]
        assert (
            "If this deployment exposes outlook_set_focused_override, use this value as `sender` "
            "in that tool"
        ) in described

    async def test_every_other_tool_it_names_comes_after_a_guard_that_names_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert _unguarded(tool) == []

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, object]", tool.output_schema)
        assert _undescribed(answer) == [], (
            "a model is handed these values with nothing to say what they are"
        )

    async def test_the_tab_is_published_as_the_two_values_a_caller_can_compare_against(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, Mapping[str, Mapping[str, object]]]", tool.output_schema)
        assert answer["$defs"]["ClassifyAs"]["enum"] == ["focused", "other"]

    def test_the_call_that_proves_the_permissions_takes_no_arguments(self) -> None:
        assert lister.GRAPH_CALL_EXAMPLE == {}


class TestGraphFailures:
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, overrides: respx.Route
    ) -> None:
        overrides.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_focused_overrides(client)

    def test_the_permissions_are_the_ones_microsoft_documents(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Mail.Read",)
