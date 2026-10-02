from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import OnenoteOwner, OnenotePageHandle, OnenoteSectionHandle
from office_365_mcp.shared.notes import (
    OWNED_REFUSED,
    PAGE_EXPANSIONS,
    PAGE_FIELDS,
    named_owner_refused,
)
from office_365_mcp.shared.seam import Advised
from office_365_mcp.tools import onenote_list_pages as lister

from .conftest import GRAPH_V1

_SECTION_ID = "0-SYNTHETICSECTION0001!0001"
_OTHER_SECTION_ID = "0-SYNTHETICSECTION0002!0001"

_PAGE_ID = "0-SYNTHETICPAGE00001!0001"
_OTHER_PAGE_ID = "0-SYNTHETICPAGE00002!0001"

_GROUP_ID = "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d"

_PAGES_PATH = "/me/onenote/pages"
_SECTION_PAGES_PATH = "/me/onenote/sections/0-SYNTHETICSECTION0001%210001/pages"
_GROUP_PAGES_PATH = f"/groups/{_GROUP_ID}/onenote/pages"
_GROUP_SECTION_PAGES_PATH = (
    f"/groups/{_GROUP_ID}/onenote/sections/0-SYNTHETICSECTION0001%210001/pages"
)

_SITE_ID = (
    "contoso.sharepoint.invalid,0d1e2f3a-0000-4000-8000-000000000001,"
    + "4b5c6d7e-0000-4000-8000-000000000002"
)
_SITE_PAGES_PATH = f"/sites/{_SITE_ID}/onenote/pages"
_SITE_SECTION_PAGES_PATH = f"/sites/{_SITE_ID}/onenote/sections/0-SYNTHETICSECTION0001%210001/pages"

_SECTION = OnenoteSectionHandle(_SECTION_ID).uri
_GROUP_SECTION = OnenoteSectionHandle(_SECTION_ID, owner=OnenoteOwner("groups", _GROUP_ID)).uri
_SITE_SECTION = OnenoteSectionHandle(_SECTION_ID, owner=OnenoteOwner("sites", _SITE_ID)).uri

_APP_ID = "WLID-000000004C12821A"


def _page_payload(
    page_id: str | None,
    *,
    title: str | None = "Q3 roadmap",
    created_at: str | None = "2026-01-04T08:11:00Z",
    last_modified_at: str | None = "2026-02-10T14:00:00Z",
    web_url: str | None = "https://onenote.example.invalid/pages/q3-roadmap",
    client_url: str | None = "onenote:https://onenote.example.invalid/pages/q3-roadmap",
    section_id: str | None = _SECTION_ID,
    section_name: str | None = "Planning",
    notebook_name: str | None = "Team Notebook",
    created_by_app_id: str | None = _APP_ID,
) -> dict[str, object]:
    return {
        "id": page_id,
        "title": title,
        "createdDateTime": created_at,
        "lastModifiedDateTime": last_modified_at,
        "createdByAppId": created_by_app_id,
        "links": {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        },
        "parentSection": (
            None if section_id is None else {"id": section_id, "displayName": section_name}
        ),
        "parentNotebook": None if notebook_name is None else {"displayName": notebook_name},
    }


def _page(*items: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(items)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


@pytest.fixture
def pages(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_PAGES_PATH)


@pytest.fixture
def section_pages(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SECTION_PAGES_PATH)


@pytest.fixture
def group_pages(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_GROUP_PAGES_PATH)


@pytest.fixture
def group_section_pages(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_GROUP_SECTION_PAGES_PATH)


@pytest.fixture
def site_pages(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SITE_PAGES_PATH)


@pytest.fixture
def site_section_pages(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SITE_SECTION_PAGES_PATH)


class TestWhatItAsks:
    async def test_no_section_asks_every_notebooks_pages(
        self, client: GraphServiceClient, pages: respx.Route, section_pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, limit=25)

        assert pages.call_count == 1
        assert section_pages.call_count == 0

    async def test_a_section_handle_asks_that_sections_pages(
        self, client: GraphServiceClient, pages: respx.Route, section_pages: respx.Route
    ) -> None:
        section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, section=_SECTION, limit=25)

        assert section_pages.call_count == 1
        assert pages.call_count == 0

    async def test_the_section_route_asks_the_same_fields_expand_top_and_filter(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, section=_SECTION, title_contains="Roadmap", limit=7)

        params = section_pages.calls.last.request.url.params
        assert params["$select"].split(",") == list(PAGE_FIELDS)
        assert params["$expand"].split(",") == list(PAGE_EXPANSIONS)
        assert params["$top"] == "7"
        assert params["$filter"] == "contains(tolower(title),'roadmap')"

    def test_the_startup_probe_calls_this_tool_with_no_arguments_at_all(self) -> None:
        assert lister.GRAPH_CALL_EXAMPLE == {}

    @pytest.mark.usefixtures("section_pages")
    async def test_it_asks_for_every_field_a_row_is_built_from(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, limit=25)

        params = pages.calls.last.request.url.params
        assert params["$select"].split(",") == list(PAGE_FIELDS)
        assert params["$expand"].split(",") == list(PAGE_EXPANSIONS)

    @pytest.mark.usefixtures("section_pages")
    async def test_it_never_orders_this_collection(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, limit=25)

        assert "$orderby" not in pages.calls.last.request.url.params

    @pytest.mark.usefixtures("section_pages")
    async def test_no_filter_when_title_contains_is_omitted(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, limit=25)

        assert "$filter" not in pages.calls.last.request.url.params

    @pytest.mark.usefixtures("section_pages")
    async def test_the_window_is_asked_of_graph_rather_than_only_applied_here(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, limit=7)

        assert pages.calls.last.request.url.params["$top"] == "7"

    @pytest.mark.usefixtures("section_pages")
    async def test_a_title_fragment_becomes_a_lowercase_contains_filter(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, title_contains="Roadmap", limit=25)

        assert (
            pages.calls.last.request.url.params["$filter"] == "contains(tolower(title),'roadmap')"
        )

    @pytest.mark.usefixtures("section_pages")
    async def test_mixed_case_is_lowercased_before_it_reaches_graph(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, title_contains="RoadMap", limit=25)

        assert (
            pages.calls.last.request.url.params["$filter"] == "contains(tolower(title),'roadmap')"
        )

    @pytest.mark.usefixtures("section_pages")
    async def test_an_apostrophe_in_a_title_fragment_cannot_end_the_odata_literal(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, title_contains="O'Brien's notes", limit=25)

        assert pages.calls.last.request.url.params["$filter"] == (
            "contains(tolower(title),'o''brien''s notes')"
        )

    @pytest.mark.usefixtures("section_pages")
    async def test_a_creating_app_becomes_an_exact_created_by_app_id_filter(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, created_by_app_id=_APP_ID, limit=25)

        assert pages.calls.last.request.url.params["$filter"] == (
            "createdByAppId eq 'WLID-000000004C12821A'"
        )

    @pytest.mark.usefixtures("section_pages")
    async def test_the_app_id_keeps_its_case_for_graph(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, created_by_app_id="Wlid-AbC", limit=25)

        assert pages.calls.last.request.url.params["$filter"] == "createdByAppId eq 'Wlid-AbC'"

    @pytest.mark.usefixtures("section_pages")
    async def test_an_apostrophe_in_an_app_id_cannot_end_the_odata_literal(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, created_by_app_id="app'id", limit=25)

        assert pages.calls.last.request.url.params["$filter"] == "createdByAppId eq 'app''id'"

    async def test_the_app_filter_reaches_the_section_route_too(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, section=_SECTION, created_by_app_id=_APP_ID, limit=25)

        assert section_pages.calls.last.request.url.params["$filter"] == (
            "createdByAppId eq 'WLID-000000004C12821A'"
        )

    @pytest.mark.parametrize("limit", [0, lister.MAX_PAGES + 1])
    async def test_a_limit_outside_the_window_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await lister.list_pages(client, limit=limit)


class TestTheGroupRoute:
    async def test_a_group_asks_that_groups_pages_and_nothing_else(
        self,
        client: GraphServiceClient,
        group_pages: respx.Route,
        pages: respx.Route,
        section_pages: respx.Route,
        group_section_pages: respx.Route,
    ) -> None:
        group_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, group=_GROUP_ID, limit=25)

        assert group_pages.call_count == 1
        assert pages.call_count == 0
        assert section_pages.call_count == 0
        assert group_section_pages.call_count == 0

    async def test_the_group_route_sends_the_query_strings_of_the_user_route(
        self, client: GraphServiceClient, group_pages: respx.Route, pages: respx.Route
    ) -> None:
        group_pages.mock(return_value=_page())
        pages.mock(return_value=_page())

        for group in (None, _GROUP_ID):
            _ = await lister.list_pages(
                client,
                group=group,
                title_contains="Roadmap",
                order_by="title_asc",
                modified_after=date(2026, 3, 4),
                created_before=date(2026, 4, 1),
                skip=10,
                limit=7,
            )

        assert group_pages.calls.last.request.url.params == pages.calls.last.request.url.params
        assert group_pages.calls.last.request.url.params["$top"] == "7"

    async def test_a_group_row_carries_the_group_in_both_of_its_handles(
        self, client: GraphServiceClient, group_pages: respx.Route
    ) -> None:
        group_pages.mock(return_value=_page(_page_payload(_PAGE_ID, section_id=_SECTION_ID)))

        answer = await lister.list_pages(client, group=_GROUP_ID, limit=25)

        row = answer.pages[0]
        assert row.uri == OnenotePageHandle(_PAGE_ID, owner=OnenoteOwner("groups", _GROUP_ID)).uri
        assert (
            row.section_uri
            == OnenoteSectionHandle(_SECTION_ID, owner=OnenoteOwner("groups", _GROUP_ID)).uri
        )
        assert row.uri.startswith(f"onenote:///groups/{_GROUP_ID}/pages/")

    async def test_a_row_of_a_call_with_no_group_names_no_group(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        answer = await lister.list_pages(client, limit=25)

        assert "/groups/" not in answer.pages[0].uri
        assert "/groups/" not in (answer.pages[0].section_uri or "")

    async def test_a_group_search_follows_a_next_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_GROUP_PAGES_PATH, params={"$skiptoken": "second"}).mock(
            return_value=_page(_page_payload(_OTHER_PAGE_ID, title="Second"))
        )
        graph.get(_GROUP_PAGES_PATH).mock(
            return_value=_page(
                _page_payload(_PAGE_ID, title="First"),
                next_link=f"{GRAPH_V1}{_GROUP_PAGES_PATH}?$skiptoken=second",
            )
        )

        answer = await lister.list_pages(client, group=_GROUP_ID, limit=25)

        assert [row.title for row in answer.pages] == ["First", "Second"]
        assert [row.uri for row in answer.pages] == [
            OnenotePageHandle(_PAGE_ID, owner=OnenoteOwner("groups", _GROUP_ID)).uri,
            OnenotePageHandle(_OTHER_PAGE_ID, owner=OnenoteOwner("groups", _GROUP_ID)).uri,
        ]

    async def test_a_group_and_a_creating_app_go_out_on_one_call_to_the_group_route(
        self, client: GraphServiceClient, group_pages: respx.Route, pages: respx.Route
    ) -> None:
        group_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        answer = await lister.list_pages(
            client,
            group=_GROUP_ID,
            created_by_app_id=_APP_ID,
            title_contains="Roadmap",
            limit=25,
        )

        assert group_pages.call_count == 1
        assert pages.call_count == 0
        assert group_pages.calls.last.request.url.params["$filter"] == (
            "contains(tolower(title),'roadmap') and createdByAppId eq 'WLID-000000004C12821A'"
        )
        assert (
            answer.pages[0].uri
            == OnenotePageHandle(_PAGE_ID, owner=OnenoteOwner("groups", _GROUP_ID)).uri
        )
        assert answer.pages[0].created_by_app_id == _APP_ID

    async def test_a_group_section_handle_and_a_creating_app_go_out_on_one_call(
        self, client: GraphServiceClient, group_section_pages: respx.Route
    ) -> None:
        group_section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        answer = await lister.list_pages(
            client, section=_GROUP_SECTION, created_by_app_id=_APP_ID, limit=25
        )

        assert group_section_pages.calls.last.request.url.params["$filter"] == (
            "createdByAppId eq 'WLID-000000004C12821A'"
        )
        assert (
            answer.pages[0].uri
            == OnenotePageHandle(_PAGE_ID, owner=OnenoteOwner("groups", _GROUP_ID)).uri
        )

    async def test_a_section_handle_of_a_group_asks_that_groups_section_route(
        self,
        client: GraphServiceClient,
        group_section_pages: respx.Route,
        group_pages: respx.Route,
        section_pages: respx.Route,
        pages: respx.Route,
    ) -> None:
        group_section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, section=_GROUP_SECTION, limit=25)

        assert group_section_pages.call_count == 1
        assert group_pages.call_count == 0
        assert section_pages.call_count == 0
        assert pages.call_count == 0

    async def test_a_section_handle_of_a_group_makes_rows_that_carry_the_group(
        self, client: GraphServiceClient, group_section_pages: respx.Route
    ) -> None:
        group_section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        answer = await lister.list_pages(client, section=_GROUP_SECTION, limit=25)

        row = answer.pages[0]
        assert row.uri == OnenotePageHandle(_PAGE_ID, owner=OnenoteOwner("groups", _GROUP_ID)).uri
        assert (
            row.section_uri
            == OnenoteSectionHandle(_SECTION_ID, owner=OnenoteOwner("groups", _GROUP_ID)).uri
        )

    async def test_level_and_order_go_out_on_the_group_section_route(
        self, client: GraphServiceClient, group_section_pages: respx.Route
    ) -> None:
        group_section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(
            client, section=_GROUP_SECTION, include_level_and_order=True, limit=7
        )

        params = group_section_pages.calls.last.request.url.params
        assert params["pagelevel"] == "true"
        assert params["$select"].split(",") == [*PAGE_FIELDS, "level", "order"]
        assert params["$top"] == "7"

    @pytest.mark.parametrize("section", [_SECTION, _GROUP_SECTION])
    async def test_a_group_together_with_a_section_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, section: str
    ) -> None:
        with pytest.raises(ToolError, match="`group` or `site` only when `section` is omitted"):
            _ = await lister.list_pages(client, section=section, group=_GROUP_ID, limit=25)

        assert len(graph.calls) == 0

    async def test_the_refusal_of_both_says_a_section_handle_carries_its_owner(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="already carries its owner") as excinfo:
            _ = await lister.list_pages(client, section=_SECTION, group=_GROUP_ID, limit=25)

        assert "fails again" in str(excinfo.value)

    async def test_a_group_with_level_and_order_but_no_section_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="section"):
            _ = await lister.list_pages(
                client, group=_GROUP_ID, include_level_and_order=True, limit=25
            )

        assert len(graph.calls) == 0

    async def test_a_404_on_the_group_route_is_a_not_found(
        self, client: GraphServiceClient, group_pages: respx.Route
    ) -> None:
        group_pages.mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.list_pages(client, group=_GROUP_ID, limit=25)

    def test_the_not_found_advice_covers_a_group_id(self) -> None:
        assert "`group`" in lister.GRAPH_NOT_FOUND
        assert (
            "names no group that the signed-in user can reach. Ask the user for the correct id."
            in lister.GRAPH_NOT_FOUND
        )
        assert "teams_list_my_teams" not in lister.GRAPH_NOT_FOUND


class TestTheSiteRoute:
    async def test_a_site_asks_that_sites_pages_and_nothing_else(
        self,
        client: GraphServiceClient,
        site_pages: respx.Route,
        pages: respx.Route,
        section_pages: respx.Route,
        group_pages: respx.Route,
        site_section_pages: respx.Route,
    ) -> None:
        site_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, site=_SITE_ID, limit=25)

        assert site_pages.call_count == 1
        assert pages.call_count == 0
        assert section_pages.call_count == 0
        assert group_pages.call_count == 0
        assert site_section_pages.call_count == 0

    async def test_the_site_route_sends_the_query_strings_of_the_user_route(
        self, client: GraphServiceClient, site_pages: respx.Route, pages: respx.Route
    ) -> None:
        site_pages.mock(return_value=_page())
        pages.mock(return_value=_page())

        for site in (None, _SITE_ID):
            _ = await lister.list_pages(
                client,
                site=site,
                title_contains="Roadmap",
                created_by_app_id=_APP_ID,
                order_by="title_asc",
                modified_after=date(2026, 3, 4),
                created_before=date(2026, 4, 1),
                skip=10,
                limit=7,
            )

        assert site_pages.calls.last.request.url.params == pages.calls.last.request.url.params
        assert site_pages.calls.last.request.url.params["$top"] == "7"

    async def test_a_site_row_carries_the_site_in_both_of_its_handles(
        self, client: GraphServiceClient, site_pages: respx.Route
    ) -> None:
        site_pages.mock(return_value=_page(_page_payload(_PAGE_ID, section_id=_SECTION_ID)))

        answer = await lister.list_pages(client, site=_SITE_ID, limit=25)

        row = answer.pages[0]
        owner = OnenoteOwner("sites", _SITE_ID)
        assert row.uri == OnenotePageHandle(_PAGE_ID, owner=owner).uri
        assert row.section_uri == OnenoteSectionHandle(_SECTION_ID, owner=owner).uri
        assert row.uri.startswith("onenote:///sites/")

    async def test_a_section_handle_of_a_site_asks_that_sites_section_route(
        self,
        client: GraphServiceClient,
        site_section_pages: respx.Route,
        site_pages: respx.Route,
        section_pages: respx.Route,
        pages: respx.Route,
    ) -> None:
        site_section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        answer = await lister.list_pages(client, section=_SITE_SECTION, limit=25)

        assert site_section_pages.call_count == 1
        assert site_pages.call_count == 0
        assert section_pages.call_count == 0
        assert pages.call_count == 0
        assert answer.pages[0].uri.startswith("onenote:///sites/")

    @pytest.mark.parametrize("section", [_SECTION, _SITE_SECTION])
    async def test_a_site_together_with_a_section_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, section: str
    ) -> None:
        with pytest.raises(ToolError, match="`group` or `site` only when `section` is omitted"):
            _ = await lister.list_pages(client, section=section, site=_SITE_ID, limit=25)

        assert len(graph.calls) == 0

    async def test_a_group_together_with_a_site_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="at most one of `group` and `site`") as excinfo:
            _ = await lister.list_pages(client, group=_GROUP_ID, site=_SITE_ID, limit=25)

        assert "never to both" in str(excinfo.value)
        assert "do not retry it as it is" in str(excinfo.value)
        assert len(graph.calls) == 0

    async def test_a_site_with_level_and_order_but_no_section_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="section"):
            _ = await lister.list_pages(
                client, site=_SITE_ID, include_level_and_order=True, limit=25
            )

        assert len(graph.calls) == 0

    async def test_a_404_on_the_site_route_is_a_not_found(
        self, client: GraphServiceClient, site_pages: respx.Route
    ) -> None:
        site_pages.mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.list_pages(client, site=_SITE_ID, limit=25)

    def test_the_not_found_advice_covers_a_site_id(self) -> None:
        assert "If this call named a `site`" in lister.GRAPH_NOT_FOUND
        assert "names no site that the signed-in user can reach" in lister.GRAPH_NOT_FOUND
        assert "This same id fails again, so do not retry it." in lister.GRAPH_NOT_FOUND


class TestWhatItAnswers:
    @pytest.mark.usefixtures("section_pages")
    async def test_a_page_becomes_a_row_with_its_handles(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(
            return_value=_page(
                _page_payload(
                    _PAGE_ID,
                    title="Q3 roadmap",
                    section_id=_SECTION_ID,
                    section_name="Planning",
                    notebook_name="Team Notebook",
                )
            )
        )

        answer = await lister.list_pages(client, limit=25)

        assert len(answer.pages) == 1
        row = answer.pages[0]
        assert row.uri == OnenotePageHandle(_PAGE_ID).uri
        assert row.section_uri == OnenoteSectionHandle(_SECTION_ID).uri
        assert row.title == "Q3 roadmap"
        assert row.section_name == "Planning"
        assert row.notebook_name == "Team Notebook"
        assert row.web_url == "https://onenote.example.invalid/pages/q3-roadmap"
        assert row.client_url == "onenote:https://onenote.example.invalid/pages/q3-roadmap"
        assert row.created_by_app_id == _APP_ID

    @pytest.mark.usefixtures("section_pages")
    async def test_a_page_graph_gave_no_creating_app_has_a_null_created_by_app_id(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID, created_by_app_id=None)))

        answer = await lister.list_pages(client, limit=25)

        assert answer.pages[0].created_by_app_id is None

    @pytest.mark.usefixtures("section_pages")
    async def test_a_page_with_no_parent_section_has_no_section_uri(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID, section_id=None, notebook_name=None)))

        answer = await lister.list_pages(client, limit=25)

        row = answer.pages[0]
        assert row.section_uri is None
        assert row.section_name is None
        assert row.notebook_name is None

    @pytest.mark.usefixtures("section_pages")
    async def test_a_page_with_no_id_is_dropped(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(
            return_value=_page(
                _page_payload(None, title="No id"),
                _page_payload(_PAGE_ID, title="Has id"),
            )
        )

        answer = await lister.list_pages(client, limit=25)

        assert [row.title for row in answer.pages] == ["Has id"]

    @pytest.mark.usefixtures("section_pages")
    async def test_the_pages_are_followed_across_a_next_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_PAGES_PATH, params={"$skiptoken": "second"}).mock(
            return_value=_page(_page_payload(_OTHER_PAGE_ID, title="Second"))
        )
        graph.get(_PAGES_PATH).mock(
            return_value=_page(
                _page_payload(_PAGE_ID, title="First"),
                next_link=f"{GRAPH_V1}{_PAGES_PATH}?$skiptoken=second",
            )
        )

        answer = await lister.list_pages(client, limit=25)

        assert [row.title for row in answer.pages] == ["First", "Second"]
        assert answer.capped is False

    @pytest.mark.usefixtures("section_pages")
    async def test_a_cap_that_left_more_on_offer_says_capped(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(
            return_value=_page(
                _page_payload(_PAGE_ID, title="First"),
                _page_payload(_OTHER_PAGE_ID, title="Second"),
            )
        )

        answer = await lister.list_pages(client, limit=1)

        assert [row.title for row in answer.pages] == ["First"]
        assert answer.capped is True

    @pytest.mark.usefixtures("section_pages")
    async def test_a_window_filled_exactly_by_the_end_of_the_collection_is_not_capped(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(
            return_value=_page(
                _page_payload(_PAGE_ID, title="First"),
                _page_payload(_OTHER_PAGE_ID, title="Second"),
            )
        )

        answer = await lister.list_pages(client, limit=2)

        assert len(answer.pages) == 2
        assert answer.capped is False

    async def test_an_empty_collection_answers_an_empty_list(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        section_pages.mock(return_value=_page())

        answer = await lister.list_pages(client, section=_SECTION, limit=25)

        assert answer.pages == []
        assert answer.capped is False


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "section",
        [
            "Planning",
            "https://onenote.example.invalid/sections/planning",
            _SECTION_ID,
            "onenote:///sections/",
            OnenotePageHandle(_PAGE_ID).uri,
        ],
    )
    async def test_a_section_that_is_not_a_section_handle_never_reaches_graph(
        self,
        client: GraphServiceClient,
        pages: respx.Route,
        section_pages: respx.Route,
        section: str,
    ) -> None:
        with pytest.raises(ToolError, match="section handle"):
            _ = await lister.list_pages(client, section=section, limit=25)

        assert pages.call_count == 0
        assert section_pages.call_count == 0

    async def test_the_refusal_says_how_to_get_a_section_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_notebooks"):
            _ = await lister.list_pages(client, section="Planning", limit=25)


class TestGraphFailures:
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.list_pages(client, limit=25)

    @pytest.mark.parametrize(
        ("group", "site", "route"),
        [(_GROUP_ID, None, _GROUP_PAGES_PATH), (None, _SITE_ID, _SITE_PAGES_PATH)],
        ids=["group", "site"],
    )
    async def test_a_refusal_for_a_named_owner_arrives_as_advice_with_the_diagnostics(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        group: str | None,
        site: str | None,
        route: str,
    ) -> None:
        graph.get(route).mock(
            return_value=httpx.Response(
                403,
                headers={"request-id": "req-7"},
                json={"error": {"code": "accessDenied", "message": "denied"}},
            )
        )

        with pytest.raises(Advised) as refused:
            _ = await lister.list_pages(client, group=group, site=site, limit=25)

        assert str(refused.value) == (
            named_owner_refused("Notes.Read")
            + " (HTTP 403, Graph error code accessDenied, Graph request id req-7)"
        )
        assert "are not the problem" not in str(refused.value)
        assert isinstance(refused.value.__cause__, GraphForbidden)

    @pytest.mark.parametrize(
        ("section", "route"),
        [
            (_GROUP_SECTION, _GROUP_SECTION_PAGES_PATH),
            (_SITE_SECTION, _SITE_SECTION_PAGES_PATH),
        ],
        ids=["group", "site"],
    )
    async def test_a_refusal_for_an_owned_section_handle_arrives_as_the_owned_advice(
        self, client: GraphServiceClient, graph: respx.MockRouter, section: str, route: str
    ) -> None:
        graph.get(route).mock(
            return_value=httpx.Response(
                403,
                headers={"request-id": "req-7"},
                json={"error": {"code": "accessDenied", "message": "denied"}},
            )
        )

        with pytest.raises(Advised) as refused:
            _ = await lister.list_pages(client, section=section, limit=25)

        assert str(refused.value) == (
            OWNED_REFUSED + " (HTTP 403, Graph error code accessDenied, Graph request id req-7)"
        )
        assert isinstance(refused.value.__cause__, GraphForbidden)

    async def test_a_refusal_for_a_section_handle_with_no_owner_stays_a_forbidden(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        section_pages.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.list_pages(client, section=_SECTION, limit=25)

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Notes.Read",)

    async def test_a_stale_section_handle_answers_not_found(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        section_pages.mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.list_pages(client, section=_SECTION, limit=25)

    def test_a_stale_section_handle_is_answered_with_the_recovery_that_works(self) -> None:
        assert "onenote_list_notebooks" in lister.GRAPH_NOT_FOUND
        assert "fails again" in lister.GRAPH_NOT_FOUND

    def test_the_not_found_advice_says_no_argument_fixes_a_missing_onenote(self) -> None:
        assert (
            "If it named none of these, Microsoft found no OneNote for this account to list "
            + "pages from at all."
            in lister.GRAPH_NOT_FOUND
        )
        assert "No other argument here fixes that." in lister.GRAPH_NOT_FOUND
        assert "at all, and no other argument" not in lister.GRAPH_NOT_FOUND


async def _ordered(client: GraphServiceClient, order_by: lister.OrderBy) -> None:
    _ = await lister.list_pages(client, order_by=order_by, limit=25)


class TestOrderBy:
    @pytest.mark.usefixtures("section_pages")
    async def test_last_modified_desc_becomes_the_matching_orderby_clause(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        await _ordered(client, "last_modified_desc")

        assert pages.calls.last.request.url.params["$orderby"] == "lastModifiedDateTime desc"

    @pytest.mark.usefixtures("section_pages")
    async def test_last_modified_asc_becomes_the_matching_orderby_clause(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        await _ordered(client, "last_modified_asc")

        assert pages.calls.last.request.url.params["$orderby"] == "lastModifiedDateTime asc"

    @pytest.mark.usefixtures("section_pages")
    async def test_created_desc_becomes_the_matching_orderby_clause(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        await _ordered(client, "created_desc")

        assert pages.calls.last.request.url.params["$orderby"] == "createdDateTime desc"

    @pytest.mark.usefixtures("section_pages")
    async def test_created_asc_becomes_the_matching_orderby_clause(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        await _ordered(client, "created_asc")

        assert pages.calls.last.request.url.params["$orderby"] == "createdDateTime asc"

    @pytest.mark.usefixtures("section_pages")
    async def test_title_asc_becomes_the_matching_orderby_clause(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        await _ordered(client, "title_asc")

        assert pages.calls.last.request.url.params["$orderby"] == "title asc"

    @pytest.mark.usefixtures("section_pages")
    async def test_title_desc_becomes_the_matching_orderby_clause(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        await _ordered(client, "title_desc")

        assert pages.calls.last.request.url.params["$orderby"] == "title desc"

    @pytest.mark.usefixtures("section_pages")
    async def test_order_by_reaches_the_section_route_too(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, section=_SECTION, order_by="title_asc", limit=25)

        assert section_pages.calls.last.request.url.params["$orderby"] == "title asc"


class TestTheTimeWindows:
    @pytest.mark.usefixtures("section_pages")
    async def test_modified_after_a_date_is_a_ge_clause_at_the_start_of_the_day(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, modified_after=date(2026, 3, 4), limit=25)

        assert pages.calls.last.request.url.params["$filter"] == (
            "lastModifiedDateTime ge 2026-03-04T00:00:00Z"
        )

    @pytest.mark.usefixtures("section_pages")
    async def test_modified_before_a_date_is_a_lt_clause_at_the_start_of_the_next_day(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, modified_before=date(2026, 3, 4), limit=25)

        assert pages.calls.last.request.url.params["$filter"] == (
            "lastModifiedDateTime lt 2026-03-05T00:00:00Z"
        )

    @pytest.mark.usefixtures("section_pages")
    async def test_modified_before_a_moment_is_a_le_clause_at_that_second(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(
            client, modified_before=datetime(2026, 3, 4, 9, 0, 0, tzinfo=UTC), limit=25
        )

        assert pages.calls.last.request.url.params["$filter"] == (
            "lastModifiedDateTime le 2026-03-04T09:00:00Z"
        )

    @pytest.mark.usefixtures("section_pages")
    async def test_created_after_and_before_use_createddatetime(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(
            client,
            created_after=date(2026, 1, 1),
            created_before=date(2026, 1, 31),
            limit=25,
        )

        assert pages.calls.last.request.url.params["$filter"] == (
            "createdDateTime ge 2026-01-01T00:00:00Z and createdDateTime lt 2026-02-01T00:00:00Z"
        )

    @pytest.mark.usefixtures("section_pages")
    async def test_a_window_and_title_contains_are_joined_with_and(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(
            client, modified_after=date(2026, 3, 4), title_contains="Roadmap", limit=25
        )

        assert pages.calls.last.request.url.params["$filter"] == (
            "lastModifiedDateTime ge 2026-03-04T00:00:00Z and contains(tolower(title),'roadmap')"
        )

    @pytest.mark.usefixtures("section_pages")
    async def test_a_window_a_title_and_an_app_are_all_joined_with_and(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(
            client,
            modified_after=date(2026, 3, 4),
            title_contains="Roadmap",
            created_by_app_id=_APP_ID,
            limit=25,
        )

        assert pages.calls.last.request.url.params["$filter"] == (
            "lastModifiedDateTime ge 2026-03-04T00:00:00Z and contains(tolower(title),'roadmap') "
            + "and createdByAppId eq 'WLID-000000004C12821A'"
        )

    async def test_a_backwards_modified_window_never_reaches_graph(
        self, client: GraphServiceClient, pages: respx.Route, section_pages: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="modified_after"):
            _ = await lister.list_pages(
                client,
                modified_after=date(2026, 3, 5),
                modified_before=date(2026, 3, 1),
                limit=25,
            )

        assert pages.call_count == 0
        assert section_pages.call_count == 0

    async def test_a_backwards_created_window_never_reaches_graph(
        self, client: GraphServiceClient, pages: respx.Route, section_pages: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="created_after"):
            _ = await lister.list_pages(
                client,
                created_after=date(2026, 3, 5),
                created_before=date(2026, 3, 1),
                limit=25,
            )

        assert pages.call_count == 0
        assert section_pages.call_count == 0


class TestSkip:
    @pytest.mark.usefixtures("section_pages")
    async def test_skip_zero_sends_no_skip(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, skip=0, limit=25)

        assert "$skip" not in pages.calls.last.request.url.params

    @pytest.mark.usefixtures("section_pages")
    async def test_a_positive_skip_is_sent(
        self, client: GraphServiceClient, pages: respx.Route
    ) -> None:
        pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, skip=10, limit=25)

        assert pages.calls.last.request.url.params["$skip"] == "10"


class TestIncludeLevelAndOrder:
    async def test_pagelevel_is_sent_raw_on_the_section_route(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(
            client, section=_SECTION, include_level_and_order=True, limit=25
        )

        assert section_pages.calls.last.request.url.params["pagelevel"] == "true"

    async def test_the_typed_parameters_still_reach_the_wire_alongside_pagelevel(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, section=_SECTION, include_level_and_order=True, limit=7)

        params = section_pages.calls.last.request.url.params
        assert params["$select"].split(",") == [*PAGE_FIELDS, "level", "order"]
        assert params["$top"] == "7"

    async def test_the_select_stays_narrow_when_level_and_order_are_not_asked_for(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        _ = await lister.list_pages(client, section=_SECTION, limit=7)

        params = section_pages.calls.last.request.url.params
        assert params["$select"].split(",") == list(PAGE_FIELDS)

    async def test_without_a_section_it_is_refused_before_reaching_graph(
        self, client: GraphServiceClient, pages: respx.Route, section_pages: respx.Route
    ) -> None:
        with pytest.raises(ToolError, match="section"):
            _ = await lister.list_pages(client, include_level_and_order=True, limit=25)

        assert pages.call_count == 0
        assert section_pages.call_count == 0

    async def test_level_and_order_flow_into_the_page_summary(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        payload = _page_payload(_PAGE_ID)
        payload["level"] = 1
        payload["order"] = 3
        section_pages.mock(return_value=_page(payload))

        answer = await lister.list_pages(
            client, section=_SECTION, include_level_and_order=True, limit=25
        )

        assert answer.pages[0].level == 1
        assert answer.pages[0].order == 3

    async def test_level_and_order_are_null_when_not_asked_for(
        self, client: GraphServiceClient, section_pages: respx.Route
    ) -> None:
        section_pages.mock(return_value=_page(_page_payload(_PAGE_ID)))

        answer = await lister.list_pages(client, section=_SECTION, limit=25)

        assert answer.pages[0].level is None
        assert answer.pages[0].order is None


class TestItsArguments:
    async def _properties(self, transport: httpx.AsyncClient) -> Mapping[str, Mapping[str, object]]:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)
        tool = await mcp.get_tool(lister.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"
        return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])

    async def test_it_takes_a_group_beside_the_section(self, transport: httpx.AsyncClient) -> None:
        properties = await self._properties(transport)

        assert {"section", "group"} <= set(properties)

    async def test_the_group_argument_says_whose_pages_it_searches_and_excludes_the_section(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = await self._properties(transport)

        described = cast("str", properties["group"]["description"])
        assert described.startswith(
            "The Microsoft 365 group or team whose pages this call searches"
        )
        assert "A team id is a group id." in described
        assert "Ask the user for it, or copy a team id from an earlier result." in described
        assert "teams_list_my_teams" not in described
        assert "only without `section`" in described
        assert 15 <= len(described.split()) <= 60

    async def test_the_section_argument_says_how_a_group_or_site_section_handle_starts(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = await self._properties(transport)

        described = cast("str", properties["section"]["description"])
        assert (
            "starts with onenote:///groups/{group}/ " + "or onenote:///sites/{site}/ instead"
            in described
        )

    async def test_it_takes_an_optional_site_beside_the_group(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = await self._properties(transport)

        assert {"section", "group", "site"} <= set(properties)
        assert properties["site"]["default"] is None
        assert {"minLength": 1, "type": "string"} in cast(
            "list[object]", properties["site"]["anyOf"]
        )

    async def test_the_site_argument_says_whose_pages_it_searches_and_how_to_write_the_id(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = await self._properties(transport)

        described = cast("str", properties["site"]["description"])
        assert described.startswith("The SharePoint site whose pages this call searches")
        assert "a host name and two ids, joined by commas, and not percent-encoded" in described
        assert "Ask the user for it." in described
        assert "only without `section`" in described
        assert "at most one of `group` and `site`" in described
        assert 15 <= len(described.split()) <= 60

    def test_the_description_names_the_group_and_site_search(self) -> None:
        assert "notebooks of one group or one SharePoint site" in lister._DESCRIPTION  # pyright: ignore[reportPrivateUsage]
