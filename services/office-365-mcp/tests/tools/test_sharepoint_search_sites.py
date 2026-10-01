from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.server.manifest import NEEDS_ADMIN_CONSENT
from office_365_mcp.shared.seam import READ_ONLY, REQUESTABLE_PERMISSIONS
from office_365_mcp.tools import sharepoint_search_files
from office_365_mcp.tools import sharepoint_search_sites as finder

from .conftest import GRAPH_V1

_SITES = "/sites"

_FINANCE = "https://contoso.sharepoint.invalid/sites/Finance"
_LEGAL = "https://contoso.sharepoint.invalid/sites/Legal"


def _site_payload(
    *,
    web_url: str | None = _FINANCE,
    display_name: str | None = "Finance Team",
    name: str | None = "Finance",
    description: str | None = "Budgets and forecasts",
) -> dict[str, object]:
    return {
        "id": "contoso.sharepoint.invalid,da60e844-ba1d-49bc-b4d4-d5e36bae9019,712a596e",
        "displayName": display_name,
        "name": name,
        "description": description,
        "webUrl": web_url,
    }


def _page(*sites: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(sites)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


@pytest.fixture
def sites(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SITES)


async def _tool_of(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    finder.register(mcp, transport)
    tool = await mcp.get_tool(finder.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


class TestTheRequestItSends:
    async def test_the_search_text_travels_as_search_and_not_as_dollar_search(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(return_value=_page(_site_payload()))

        _ = await finder.search_sites(client, query="finance", limit=25)

        request = sites.calls.last.request
        assert request.url.params["search"] == "finance"
        assert "$search" not in request.url.params
        assert "search=finance" in str(request.url)
        assert "%24search" not in str(request.url)

    async def test_a_query_with_a_space_and_an_ampersand_arrives_as_one_value(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(return_value=_page(_site_payload()))

        _ = await finder.search_sites(client, query="Q3 budget & plan", limit=25)

        assert sites.calls.last.request.url.params["search"] == "Q3 budget & plan"

    async def test_it_sends_no_option_that_the_search_page_does_not_document(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(return_value=_page(_site_payload()))

        _ = await finder.search_sites(client, query="finance", limit=7)

        assert set(sites.calls.last.request.url.params) == {"search"}

    async def test_it_costs_one_graph_request(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(return_value=_page(_site_payload()))

        _ = await finder.search_sites(client, query="finance", limit=25)

        assert sites.call_count == 1

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_a_limit_below_one_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await finder.search_sites(client, query="finance", limit=limit)

    def test_the_startup_probe_calls_this_tool_with_one_query(self) -> None:
        assert finder.GRAPH_CALL_EXAMPLE == {"query": "finance"}


class TestWhatItAnswers:
    async def test_a_site_becomes_a_row_with_the_address_path_takes(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(return_value=_page(_site_payload()))

        answer = await finder.search_sites(client, query="finance", limit=25)

        assert [row.model_dump() for row in answer.sites] == [
            {
                "web_url": _FINANCE,
                "display_name": "Finance Team",
                "description": "Budgets and forecasts",
            }
        ]
        assert answer.capped is False

    async def test_a_site_with_no_display_name_shows_its_name(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(return_value=_page(_site_payload(display_name=None, name="Finance")))

        answer = await finder.search_sites(client, query="finance", limit=25)

        assert answer.sites[0].display_name == "Finance"

    async def test_a_site_graph_named_nothing_for_answers_nulls(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(
            return_value=_page(_site_payload(display_name=None, name=None, description=None))
        )

        row = (await finder.search_sites(client, query="finance", limit=25)).sites[0]

        assert row.display_name is None
        assert row.description is None

    async def test_an_empty_description_answers_null_and_not_empty_text(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(return_value=_page(_site_payload(description="")))

        row = (await finder.search_sites(client, query="finance", limit=25)).sites[0]

        assert row.description is None

    async def test_a_site_with_no_web_address_is_left_out(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(
            return_value=_page(
                _site_payload(web_url=None, display_name="Nameless"),
                _site_payload(web_url=_LEGAL, display_name="Legal"),
            )
        )

        answer = await finder.search_sites(client, query="team", limit=25)

        assert [row.display_name for row in answer.sites] == ["Legal"]

    async def test_the_rows_keep_the_order_graph_answered_in(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(
            return_value=_page(
                _site_payload(web_url=_LEGAL, display_name="Legal"),
                _site_payload(web_url=_FINANCE, display_name="Finance"),
            )
        )

        answer = await finder.search_sites(client, query="team", limit=25)

        assert [row.web_url for row in answer.sites] == [_LEGAL, _FINANCE]

    async def test_a_search_that_matched_nothing_is_an_empty_list_and_not_capped(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(return_value=_page())

        answer = await finder.search_sites(client, query="nothing", limit=25)

        assert answer.sites == []
        assert answer.capped is False

    async def test_the_pages_of_the_search_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_SITES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_site_payload(web_url=_LEGAL, display_name="Legal"))
        )
        graph.get(_SITES).mock(
            return_value=_page(
                _site_payload(web_url=_FINANCE, display_name="Finance"),
                next_link=f"{GRAPH_V1}{_SITES}?$skiptoken=second",
            )
        )

        answer = await finder.search_sites(client, query="team", limit=25)

        assert [row.display_name for row in answer.sites] == ["Finance", "Legal"]
        assert answer.capped is False

    async def test_a_limit_that_left_more_sites_on_offer_says_capped(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(
            return_value=_page(
                _site_payload(web_url=_FINANCE, display_name="Finance"),
                _site_payload(web_url=_LEGAL, display_name="Legal"),
            )
        )

        answer = await finder.search_sites(client, query="team", limit=1)

        assert [row.display_name for row in answer.sites] == ["Finance"]
        assert answer.capped is True


class TestGraphFailures:
    async def test_a_refused_search_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, sites: respx.Route
    ) -> None:
        sites.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await finder.search_sites(client, query="finance", limit=25)


class TestTheNewScopeStaysInThisTool:
    def test_the_tool_asks_for_sites_read_all_and_no_file_permission(self) -> None:
        assert finder.GRAPH_PERMISSIONS == ("Sites.Read.All",)

    def test_the_file_search_keeps_the_permission_it_always_had(self) -> None:
        assert sharepoint_search_files.GRAPH_PERMISSIONS == ("Files.Read.All",)

    def test_the_seam_lets_the_connector_request_the_scope(self) -> None:
        assert "Sites.Read.All" in REQUESTABLE_PERMISSIONS

    def test_the_manifest_tells_an_operator_that_an_administrator_grants_it(self) -> None:
        assert NEEDS_ADMIN_CONSENT["Sites.Read.All"] is True


class TestHowItDeclaresItself:
    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        tool = await _tool_of(transport)

        assert tool.annotations is not None, "a tool with no annotations joins the write surface"
        assert tool.annotations.read_only_hint is READ_ONLY["readOnlyHint"]

    async def test_query_is_the_one_required_argument_and_limit_defaults_to_25(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _tool_of(transport)

        properties = cast("dict[str, dict[str, object]]", tool.parameters["properties"])
        assert set(properties) == {"query", "limit"}
        assert tool.parameters["required"] == ["query"]
        assert properties["query"]["minLength"] == 1
        assert properties["limit"]["minimum"] == 1
        assert properties["limit"]["default"] == 25

    async def test_the_description_sends_a_model_on_to_the_file_search_with_a_path(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _tool_of(transport)

        description = tool.description or ""
        assert "Pass `web_url` as `path` to sharepoint_search_files" in description
        assert "It does not find files or folders." in description
        assert "\n\nNotes:\n- " in description

    async def test_the_description_has_the_house_length(self, transport: httpx.AsyncClient) -> None:
        tool = await _tool_of(transport)

        assert 45 <= len((tool.description or "").split()) <= 210

    def test_the_address_field_says_what_to_do_with_it(self) -> None:
        described = finder.SiteSummary.model_fields["web_url"].description or ""

        assert "Pass it as `path` to sharepoint_search_files to search only this site." in described
