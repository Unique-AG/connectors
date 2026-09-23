from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.tools import outlook_list_categories as lister

from .conftest import GRAPH_V1

_CATEGORIES = "/me/outlook/masterCategories"


def _category_payload(
    *, display_name: str = "Follow up", color: str | None = "preset0"
) -> dict[str, object]:
    return {"displayName": display_name, "color": color}


def _page(*categories: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(categories)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _fields(node: object, at: str, *, root: Mapping[str, object]) -> dict[str, object]:
    """Pydantic publishes a nested model as a `$ref` into the schema's own `$defs` rather than
    inline, so a walk that skips it checks only the top level and calls that the whole answer."""
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
def categories(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_CATEGORIES)


class TestTheQueryItComposes:
    async def test_it_asks_for_only_name_and_color(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=_page(_category_payload()))

        _ = await lister.list_categories(client)

        assert categories.calls.last.request.url.params["$select"].split(",") == [
            "displayName",
            "color",
        ]

    async def test_the_window_is_asked_of_graph_rather_than_only_applied_here(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=_page(_category_payload()))

        _ = await lister.list_categories(client)

        assert categories.calls.last.request.url.params["$top"] == str(lister.MAX_CATEGORIES)

    async def test_no_filter_or_ordering_narrows_the_mailboxs_own_list(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=_page(_category_payload()))

        _ = await lister.list_categories(client)

        params = categories.calls.last.request.url.params
        assert "$filter" not in params
        assert "$orderby" not in params
        assert "$expand" not in params

    async def test_the_read_happens_exactly_once(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=_page(_category_payload(display_name="Follow up")))

        _ = await lister.list_categories(client)

        assert categories.call_count == 1


class TestWhatItAnswers:
    async def test_it_reports_the_name_a_message_writes_categories_back_by(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(
            return_value=_page(_category_payload(display_name="Confidential", color="preset4"))
        )

        row = (await lister.list_categories(client)).categories[0]

        assert row.name == "Confidential"

    async def test_the_color_reads_as_its_wire_value_and_not_the_enum_members_own_repr(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        """Regression for the kiota trap `shared/calendar.py`'s `spelled` exists for on a
        different enum family: `CategoryColor` mixes in `str` without being a `StrEnum`, so a
        plain `str()` of the deserialized member answers `CategoryColor.Preset3`, not `preset3`,
        unless the tool reads it through `str.__str__` instead."""
        categories.mock(return_value=_page(_category_payload(color="preset3")))

        row = (await lister.list_categories(client)).categories[0]

        assert row.color == "preset3"

    async def test_the_explicit_none_color_is_the_literal_string_not_a_null(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        """Graph's `CategoryColor.None_` is a real, assigned value — a category somebody chose
        not to color — and it must not collapse into the different, rarer case of Graph naming no
        color property at all."""
        categories.mock(return_value=_page(_category_payload(color="none")))

        row = (await lister.list_categories(client)).categories[0]

        assert row.color == "none"

    async def test_a_category_graph_named_no_color_for_answers_a_null_color(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=_page(_category_payload(color=None)))

        row = (await lister.list_categories(client)).categories[0]

        assert row.color is None

    async def test_the_pages_of_the_listing_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The cursor route is registered before the bare one, which respx matches in registration
        order: the bare path matches a `$skiptoken` request too, and answers every page."""
        graph.get(_CATEGORIES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_category_payload(display_name="Confidential"))
        )
        graph.get(_CATEGORIES).mock(
            return_value=_page(
                _category_payload(display_name="Follow up"),
                next_link=f"{GRAPH_V1}{_CATEGORIES}?$skiptoken=second",
            )
        )

        listed = await lister.list_categories(client)

        assert [row.name for row in listed.categories] == ["Follow up", "Confidential"]
        assert listed.capped is False, "the walk reached the end of the listing"

    async def test_a_cap_that_left_more_categories_on_offer_says_capped(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_CATEGORIES", 1)
        graph.get(_CATEGORIES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_category_payload(display_name="Confidential"))
        )
        graph.get(_CATEGORIES).mock(
            return_value=_page(
                _category_payload(display_name="Follow up"),
                next_link=f"{GRAPH_V1}{_CATEGORIES}?$skiptoken=second",
            )
        )

        listed = await lister.list_categories(client)

        assert [row.name for row in listed.categories] == ["Follow up"]
        assert listed.capped is True

    async def test_a_mailbox_with_no_categories_answers_an_empty_listing(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=_page())

        listed = await lister.list_categories(client)

        assert listed.categories == []
        assert listed.capped is False, "an empty listing is the whole of it, not a cap"


class TestTheSchemaItPublishes:
    async def test_it_publishes_no_arguments_at_all(self, transport: httpx.AsyncClient) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters.get("properties", {}) == {}
        assert tool.parameters.get("required", []) == []

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, object]", tool.output_schema)
        published = _fields(answer, lister.TOOL_NAME, root=answer)
        # Guards the guard: a walk that stopped descending passes by finding nothing to check.
        assert f"{lister.TOOL_NAME}.categories[].color" in published
        undescribed = sorted(
            path
            for path, field in published.items()
            if not cast("Mapping[str, object]", field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"

    def test_the_call_that_proves_the_permissions_takes_no_arguments(self) -> None:
        """The startup probe calls this tool with the example verbatim. A tool with no arguments
        reaches Graph on the empty mapping, so the empty mapping is the whole example."""
        assert lister.GRAPH_CALL_EXAMPLE == {}


class TestGraphFailures:
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, categories: respx.Route
    ) -> None:
        categories.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_categories(client)

    def test_the_permissions_are_the_ones_microsoft_documents(self) -> None:
        """Microsoft's own permissions table for `GET /users/{id}/outlook/masterCategories`
        names only `MailboxSettings.Read`, delegated, with every higher-privileged alternative
        "Not available" — there is no `.Shared` sibling to add beside it, unlike the `Mail.*` and
        `Calendars.*` families this connector's other mailbox-targeting tools use."""
        assert lister.GRAPH_PERMISSIONS == ("MailboxSettings.Read",)
