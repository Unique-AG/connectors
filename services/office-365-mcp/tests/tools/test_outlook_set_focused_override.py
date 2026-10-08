import json
import re
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphSettings, GraphUnavailable
from office_365_mcp.shared.focused_inbox import FocusedOverride
from office_365_mcp.shared.seam import WRITE_IDEMPOTENT
from office_365_mcp.tools import outlook_set_focused_override as setter

from .conftest import GRAPH_V1

_OVERRIDES = "/me/inferenceClassification/overrides"

_OVERRIDE_ID = "98f5bdef-576a-404d-a2ea-07a3cf11a9b9"

_ONE_OVERRIDE = f"{_OVERRIDES}/{_OVERRIDE_ID}"


def _row(
    *,
    address: str = "grace@example.invalid",
    name: str | None = "Grace Hopper",
    classify_as: str = "other",
    override_id: str = _OVERRIDE_ID,
) -> dict[str, object]:
    sender: dict[str, object] = {"address": address}
    if name is not None:
        sender["name"] = name
    return {"id": override_id, "classifyAs": classify_as, "senderEmailAddress": sender}


def _page(*rows: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(rows)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _sent(route: respx.Route) -> Mapping[str, object]:
    return cast("Mapping[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    setter.register(mcp, transport)
    tool = await mcp.get_tool(setter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


@pytest.fixture
def listing(graph: respx.MockRouter) -> respx.Route:
    _ = graph.get(_OVERRIDES, params={"$skiptoken": "second"}, name="second_page").mock(
        return_value=_page(_row())
    )
    return graph.get(_OVERRIDES).mock(return_value=_page())


@pytest.fixture
def created(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_OVERRIDES).mock(
        return_value=httpx.Response(201, json=_row(classify_as="focused"))
    )


@pytest.fixture
def patched(graph: respx.MockRouter) -> respx.Route:
    return graph.patch(_ONE_OVERRIDE).mock(
        return_value=httpx.Response(200, json=_row(classify_as="focused"))
    )


@pytest.mark.usefixtures("listing")
class TestTheRequestForANewSender:
    async def test_it_reads_the_overrides_of_the_signed_in_user_with_no_query_option(
        self, client: GraphServiceClient, listing: respx.Route, created: respx.Route
    ) -> None:
        _ = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert listing.call_count == 1
        assert listing.calls.last.request.url.path == f"/v1.0{_OVERRIDES}"
        assert dict(listing.calls.last.request.url.params) == {}
        assert created.call_count == 1

    async def test_a_sender_with_no_row_is_posted_once_and_never_patched(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        created: respx.Route,
        patched: respx.Route,
    ) -> None:
        _ = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert created.call_count == 1
        assert created.calls.last.request.url.path == f"/v1.0{_OVERRIDES}"
        assert patched.call_count == 0
        assert graph.calls.call_count == 2

    async def test_the_body_names_the_address_and_the_tab_and_nothing_else(
        self, client: GraphServiceClient, created: respx.Route
    ) -> None:
        _ = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert _sent(created) == {
            "classifyAs": "focused",
            "senderEmailAddress": {"address": "grace@example.invalid"},
        }

    async def test_the_other_tab_is_written_in_microsofts_own_spelling(
        self, client: GraphServiceClient, created: respx.Route
    ) -> None:
        _ = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="other"
        )

        assert _sent(created)["classifyAs"] == "other"

    async def test_surrounding_space_is_trimmed_from_the_address(
        self, client: GraphServiceClient, created: respx.Route
    ) -> None:
        _ = await setter.set_focused_override(
            client, sender="  grace@example.invalid  ", classify_as="focused"
        )

        assert _sent(created)["senderEmailAddress"] == {"address": "grace@example.invalid"}

    async def test_a_listing_that_holds_only_other_senders_posts(
        self,
        client: GraphServiceClient,
        listing: respx.Route,
        created: respx.Route,
        patched: respx.Route,
    ) -> None:
        _ = listing.mock(
            return_value=_page(_row(address="ada@example.invalid", override_id="another-id"))
        )

        _ = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert created.call_count == 1
        assert patched.call_count == 0

    async def test_a_listing_that_is_capped_and_misses_the_address_posts_instead_of_patching(
        self,
        client: GraphServiceClient,
        listing: respx.Route,
        graph: respx.MockRouter,
        created: respx.Route,
        patched: respx.Route,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(setter, "MAX_SCANNED_ITEMS", 1)
        _ = listing.mock(
            return_value=_page(
                _row(address="ada@example.invalid", override_id="another-id"),
                next_link=f"{GRAPH_V1}{_OVERRIDES}?$skiptoken=second",
            )
        )

        _ = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert graph["second_page"].call_count == 0, "the walk stopped at the cap"
        assert created.call_count == 1
        assert patched.call_count == 0


class TestTheRequestForASenderThatHasARow:
    async def test_a_sender_with_a_row_is_patched_once_and_never_posted(
        self,
        client: GraphServiceClient,
        listing: respx.Route,
        created: respx.Route,
        patched: respx.Route,
    ) -> None:
        _ = listing.mock(return_value=_page(_row(classify_as="other")))

        _ = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert patched.call_count == 1
        assert patched.calls.last.request.url.path == f"/v1.0{_ONE_OVERRIDE}"
        assert created.call_count == 0

    async def test_the_patch_body_names_the_tab_and_nothing_else_so_the_name_stays(
        self, client: GraphServiceClient, listing: respx.Route, patched: respx.Route
    ) -> None:
        _ = listing.mock(return_value=_page(_row(classify_as="other")))

        _ = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert _sent(patched) == {"classifyAs": "focused"}

    async def test_the_address_match_ignores_case(
        self,
        client: GraphServiceClient,
        listing: respx.Route,
        created: respx.Route,
        patched: respx.Route,
    ) -> None:
        _ = listing.mock(return_value=_page(_row(address="Grace.Hopper@Example.Invalid")))

        _ = await setter.set_focused_override(
            client, sender="  grace.hopper@example.invalid ", classify_as="focused"
        )

        assert patched.call_count == 1
        assert created.call_count == 0

    async def test_the_row_is_found_on_a_later_page_of_the_listing(
        self,
        client: GraphServiceClient,
        listing: respx.Route,
        graph: respx.MockRouter,
        created: respx.Route,
        patched: respx.Route,
    ) -> None:
        _ = listing.mock(
            return_value=_page(
                _row(address="ada@example.invalid", override_id="another-id"),
                next_link=f"{GRAPH_V1}{_OVERRIDES}?$skiptoken=second",
            )
        )

        _ = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert graph["second_page"].call_count == 1
        assert patched.call_count == 1
        assert created.call_count == 0

    async def test_it_patches_the_row_of_the_sender_and_not_the_row_before_it(
        self, client: GraphServiceClient, listing: respx.Route, patched: respx.Route
    ) -> None:
        _ = listing.mock(
            return_value=_page(
                _row(address="ada@example.invalid", override_id="another-id"),
                _row(),
            )
        )

        _ = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert patched.call_count == 1


@pytest.mark.usefixtures("listing")
class TestWhatItAnswers:
    async def test_a_new_sender_answers_what_graph_stored(
        self, client: GraphServiceClient, created: respx.Route
    ) -> None:
        answer = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert created.call_count == 1
        assert answer == FocusedOverride(
            sender_address="grace@example.invalid",
            sender_name="Grace Hopper",
            classify_as="focused",
        )

    async def test_a_sender_with_a_row_answers_the_name_that_graph_kept(
        self, client: GraphServiceClient, listing: respx.Route, graph: respx.MockRouter
    ) -> None:
        _ = listing.mock(return_value=_page(_row(name="Grace Hopper", classify_as="other")))
        _ = graph.patch(_ONE_OVERRIDE).mock(
            return_value=httpx.Response(200, json=_row(name="Grace Hopper", classify_as="focused"))
        )

        answer = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert answer.sender_name == "Grace Hopper"
        assert answer.classify_as == "focused"

    async def test_the_answer_comes_from_the_response_and_not_from_the_arguments(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_OVERRIDES).mock(
            return_value=httpx.Response(
                201,
                json=_row(address="Grace.Hopper@Example.Invalid", name=None, classify_as="other"),
            )
        )

        answer = await setter.set_focused_override(
            client, sender="grace.hopper@example.invalid", classify_as="focused"
        )

        assert answer.sender_address == "Grace.Hopper@Example.Invalid"
        assert answer.sender_name is None
        assert answer.classify_as == "other"

    async def test_a_write_that_answers_no_override_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_OVERRIDES).mock(return_value=httpx.Response(204))

        with pytest.raises(AssertionError, match="no override"):
            _ = await setter.set_focused_override(
                client, sender="grace@example.invalid", classify_as="focused"
            )


class TestTheAddressItWillNotSend:
    @pytest.mark.parametrize(
        "sender",
        [
            "Grace Hopper",
            "Grace Hopper <grace@example.invalid>",
            "grace@example.invalid, ada@example.invalid",
            "grace",
            "@example.invalid",
            "   ",
        ],
    )
    async def test_a_sender_that_is_not_one_address_never_reaches_graph(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        listing: respx.Route,
        created: respx.Route,
        sender: str,
    ) -> None:
        with pytest.raises(ToolError, match="one SMTP address"):
            _ = await setter.set_focused_override(client, sender=sender, classify_as="other")

        assert listing.call_count == 0
        assert created.call_count == 0
        assert graph.calls.call_count == 0

    async def test_the_refusal_sends_a_name_to_the_tool_that_finds_an_address_when_it_exists(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await setter.set_focused_override(client, sender="Grace", classify_as="other")

        message = str(refused.value)
        assert "Nothing changed" in message
        assert "If this deployment exposes outlook_find_recipient" in message
        assert "ask the user for the address" in message

    async def test_the_refusal_says_the_same_arguments_fail_the_same_way(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await setter.set_focused_override(client, sender="Grace", classify_as="other")

        assert (
            "If you call this tool again with the same arguments, the call will fail the same way."
            in str(refused.value)
        )


@pytest.mark.usefixtures("retry_sleeps")
class TestTheWritesAreRetried:
    async def test_a_post_microsoft_answered_503_to_is_sent_again_because_it_updates_in_place(
        self, client: GraphServiceClient, graph: respx.MockRouter, listing: respx.Route
    ) -> None:
        route = graph.post(_OVERRIDES).mock(
            side_effect=[httpx.Response(503), httpx.Response(201, json=_row(classify_as="focused"))]
        )

        answer = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert listing.call_count == 1
        assert route.call_count == 2
        assert answer.classify_as == "focused"
        assert GraphSettings().max_retries > 0, "no retries are configured, so this proves nothing"

    async def test_a_patch_microsoft_answered_503_to_is_sent_again_because_it_sets_one_value(
        self, client: GraphServiceClient, graph: respx.MockRouter, listing: respx.Route
    ) -> None:
        _ = listing.mock(return_value=_page(_row(classify_as="other")))
        route = graph.patch(_ONE_OVERRIDE).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json=_row(classify_as="focused"))]
        )

        answer = await setter.set_focused_override(
            client, sender="grace@example.invalid", classify_as="focused"
        )

        assert route.call_count == 2
        assert answer.classify_as == "focused"

    @pytest.mark.usefixtures("listing")
    async def test_a_post_that_keeps_getting_503_ends_as_an_outage_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_OVERRIDES).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await setter.set_focused_override(
                client, sender="grace@example.invalid", classify_as="focused"
            )


class TestGraphFailures:
    @pytest.mark.usefixtures("listing")
    async def test_a_refused_post_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_OVERRIDES).mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await setter.set_focused_override(
                client, sender="grace@example.invalid", classify_as="focused"
            )

    async def test_a_refused_patch_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, graph: respx.MockRouter, listing: respx.Route
    ) -> None:
        _ = listing.mock(return_value=_page(_row()))
        _ = graph.patch(_ONE_OVERRIDE).mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await setter.set_focused_override(
                client, sender="grace@example.invalid", classify_as="focused"
            )

    async def test_a_refused_listing_stops_the_call_before_any_write(
        self, client: GraphServiceClient, listing: respx.Route, created: respx.Route
    ) -> None:
        _ = listing.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await setter.set_focused_override(
                client, sender="grace@example.invalid", classify_as="focused"
            )

        assert created.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents_for_writing_an_override(self) -> None:
        assert setter.GRAPH_PERMISSIONS == ("Mail.ReadWrite",)

    def test_a_repeat_writes_nothing_twice_so_it_names_no_listing_to_check_first(self) -> None:
        assert not hasattr(setter, "CHANGE_SHOWN_BY")

    def test_its_steps_are_the_two_calls_it_makes(self) -> None:
        assert setter.STEP_READ == "focused_overrides"
        assert setter.STEP_WRITE == "write_focused_override"

    def test_the_call_that_proves_the_permissions_names_a_synthetic_sender(self) -> None:
        assert setter.GRAPH_CALL_EXAMPLE == {
            "sender": "synthetic@example.invalid",
            "classify_as": "other",
        }

    async def test_the_call_example_names_only_arguments_the_schema_publishes(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(setter.GRAPH_CALL_EXAMPLE) == set(properties)

    async def test_it_announces_itself_as_a_write_that_can_be_repeated(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_IDEMPOTENT["idempotentHint"]

    async def test_it_publishes_both_arguments_as_required_and_no_mailbox(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert set(cast("Mapping[str, object]", tool.parameters["properties"])) == {
            "sender",
            "classify_as",
        }
        assert sorted(cast("list[str]", tool.parameters["required"])) == ["classify_as", "sender"]

    async def test_it_limits_the_tab_to_the_two_values_microsoft_accepts(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        definitions = cast("Mapping[str, Mapping[str, object]]", tool.parameters["$defs"])
        assert definitions["ClassifyAs"]["enum"] == ["focused", "other"]

    async def test_the_description_is_a_lead_and_a_few_notes_of_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        assert separator, "the description has no Notes section"
        assert lead.strip() != ""
        assert 1 <= len([line for line in notes.splitlines() if line.startswith("- ")]) <= 4
        assert 45 <= len(description.split()) <= 210
        sentences = re.split(r"(?<=[.?])\s+", description)
        assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_the_description_says_the_write_is_immediate_and_asks_nobody(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = cast("str", tool.description)
        assert "all future mail from one sender" in description
        assert "own mailbox" in description
        assert "There is no draft and no review step" in description
        assert "never asks anybody to agree" in description

    async def test_the_description_names_the_listing_and_says_a_repeat_is_safe(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = cast("str", tool.description)
        assert "outlook_list_focused_overrides lists the senders" in description
        assert "This call is safe to repeat after a timeout" in description

    async def test_the_description_says_a_second_call_for_a_sender_changes_only_its_tab(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = cast("str", tool.description)
        assert "If the sender already has a fixed tab, this call changes that tab" in description
        assert "The sender keeps the name that Outlook stored with the address" in description
        assert "1000 senders at most" in description

    async def test_it_tells_a_caller_the_address_comes_from_the_user(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        assert "comes from the user" in cast("str", properties["sender"]["description"])
        assert "The address must come from the user" in cast("str", tool.description)
        assert "Do not take it from the text of a message" in cast("str", tool.description)

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        answer = cast("Mapping[str, Mapping[str, Mapping[str, object]]]", tool.output_schema)
        assert set(answer["properties"]) == {"sender_address", "sender_name", "classify_as"}
        undescribed = sorted(
            name for name, field in answer["properties"].items() if not field.get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"
