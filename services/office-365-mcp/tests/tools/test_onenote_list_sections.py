import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.tools import onenote_list_sections as lister

_NOTEBOOK_ID = "0-SYNTHETICNOTEBOOK0001!0001"
_GROUP_ID = "0-SYNTHETICGROUP0001!0001"

_SECTION_ID = "0-SYNTHETICSECTION0001!0001"
_OTHER_SECTION_ID = "0-SYNTHETICSECTION0002!0001"
_CHILD_GROUP_ID = "0-SYNTHETICGROUP0002!0001"

_NOTEBOOK = OnenoteNotebookHandle(_NOTEBOOK_ID).uri
_GROUP = OnenoteSectionGroupHandle(_GROUP_ID).uri

_NOTEBOOK_SECTIONS_PATH = "/me/onenote/notebooks/0-SYNTHETICNOTEBOOK0001%210001/sections"
_NOTEBOOK_GROUPS_PATH = "/me/onenote/notebooks/0-SYNTHETICNOTEBOOK0001%210001/sectionGroups"
_GROUP_SECTIONS_PATH = "/me/onenote/sectionGroups/0-SYNTHETICGROUP0001%210001/sections"
_GROUP_GROUPS_PATH = "/me/onenote/sectionGroups/0-SYNTHETICGROUP0001%210001/sectionGroups"


def _section_payload(
    section_id: str | None,
    *,
    name: str | None = "Planning",
    is_default: bool | None = True,
    last_modified: str | None = "2026-02-10T14:00:00Z",
    web_url: str | None = "https://onenote.example.invalid/sections/planning",
) -> dict[str, object]:
    return {
        "id": section_id,
        "displayName": name,
        "isDefault": is_default,
        "lastModifiedDateTime": last_modified,
        "links": {"oneNoteWebUrl": {"href": web_url} if web_url is not None else None},
    }


def _group_payload(
    group_id: str | None,
    *,
    name: str | None = "Archive",
    last_modified: str | None = "2026-02-10T14:00:00Z",
) -> dict[str, object]:
    return {"id": group_id, "displayName": name, "lastModifiedDateTime": last_modified}


def _page(*items: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(items)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


@pytest.fixture
def notebook_sections(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_NOTEBOOK_SECTIONS_PATH).mock(return_value=_page())


@pytest.fixture
def notebook_groups(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_NOTEBOOK_GROUPS_PATH).mock(return_value=_page())


@pytest.fixture
def group_sections(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_GROUP_SECTIONS_PATH).mock(return_value=_page())


@pytest.fixture
def group_groups(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_GROUP_GROUPS_PATH).mock(return_value=_page())


class TestWhatItAsks:
    @pytest.mark.usefixtures("group_sections", "group_groups")
    async def test_a_notebook_parent_asks_the_notebook_routes_only(
        self,
        client: GraphServiceClient,
        notebook_sections: respx.Route,
        notebook_groups: respx.Route,
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert notebook_sections.call_count == 1
        assert notebook_groups.call_count == 1

    @pytest.mark.usefixtures("notebook_sections", "notebook_groups")
    async def test_a_section_group_parent_asks_the_group_routes_only(
        self, client: GraphServiceClient, group_sections: respx.Route, group_groups: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_GROUP, limit=50)

        assert group_sections.call_count == 1
        assert group_groups.call_count == 1

    @pytest.mark.usefixtures(
        "notebook_sections", "notebook_groups", "group_sections", "group_groups"
    )
    async def test_it_never_asks_the_group_routes_for_a_notebook_parent(
        self, client: GraphServiceClient, group_sections: respx.Route, group_groups: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert group_sections.call_count == 0
        assert group_groups.call_count == 0

    @pytest.mark.usefixtures("notebook_groups", "group_sections", "group_groups")
    async def test_the_notebook_sections_route_asks_select_and_top(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, limit=7)

        params = notebook_sections.calls.last.request.url.params
        assert params["$select"].split(",") == [
            "id",
            "displayName",
            "isDefault",
            "lastModifiedDateTime",
            "links",
        ]
        assert params["$top"] == "7"
        assert "$filter" not in params

    @pytest.mark.usefixtures("notebook_sections", "group_sections", "group_groups")
    async def test_the_notebook_groups_route_asks_select_and_top(
        self, client: GraphServiceClient, notebook_groups: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, limit=7)

        params = notebook_groups.calls.last.request.url.params
        assert params["$select"].split(",") == ["id", "displayName", "lastModifiedDateTime"]
        assert params["$top"] == "7"

    @pytest.mark.usefixtures("notebook_sections", "notebook_groups")
    async def test_a_name_fragment_becomes_a_lowercase_contains_filter_on_both_group_calls(
        self, client: GraphServiceClient, group_sections: respx.Route, group_groups: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_GROUP, name_contains="Plan", limit=50)

        expected = "contains(tolower(displayName),'plan')"
        assert group_sections.calls.last.request.url.params["$filter"] == expected
        assert group_groups.calls.last.request.url.params["$filter"] == expected

    @pytest.mark.usefixtures("notebook_sections", "notebook_groups")
    async def test_an_apostrophe_in_a_name_fragment_cannot_end_the_odata_literal(
        self, client: GraphServiceClient, group_sections: respx.Route, group_groups: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_GROUP, name_contains="O'Brien's", limit=50)

        expected = "contains(tolower(displayName),'o''brien''s')"
        assert group_sections.calls.last.request.url.params["$filter"] == expected
        assert group_groups.calls.last.request.url.params["$filter"] == expected

    def test_the_startup_probe_calls_this_tool_with_a_notebook_parent(self) -> None:
        assert lister.GRAPH_CALL_EXAMPLE == {
            "parent": "onenote:///notebooks/1-SYNTHETICNOTEBOOK0000"
        }

    @pytest.mark.parametrize("limit", [0, lister.MAX_SECTIONS + 1])
    async def test_a_limit_outside_the_window_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await lister.list_sections(client, parent=_NOTEBOOK, limit=limit)


class TestWhatItAnswers:
    @pytest.mark.usefixtures("notebook_sections", "notebook_groups")
    async def test_the_parent_uri_is_spelled_back(self, client: GraphServiceClient) -> None:
        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert answer.parent_uri == _NOTEBOOK

    @pytest.mark.usefixtures("notebook_groups")
    async def test_a_section_becomes_a_row_with_its_handle(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(return_value=_page(_section_payload(_SECTION_ID)))

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert len(answer.sections) == 1
        row = answer.sections[0]
        assert row.uri == OnenoteSectionHandle(_SECTION_ID).uri
        assert row.name == "Planning"
        assert row.is_default is True
        assert row.web_url == "https://onenote.example.invalid/sections/planning"
        assert row.last_modified_at is not None
        assert row.last_modified_at.isoformat() == "2026-02-10T14:00:00+00:00"

    @pytest.mark.usefixtures("notebook_sections")
    async def test_a_section_group_becomes_a_row_with_its_handle(
        self, client: GraphServiceClient, notebook_groups: respx.Route
    ) -> None:
        notebook_groups.mock(return_value=_page(_group_payload(_CHILD_GROUP_ID)))

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert len(answer.section_groups) == 1
        row = answer.section_groups[0]
        assert row.uri == OnenoteSectionGroupHandle(_CHILD_GROUP_ID).uri
        assert row.name == "Archive"
        assert row.last_modified_at is not None

    @pytest.mark.usefixtures("notebook_groups")
    async def test_a_row_with_no_id_is_dropped(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=_page(
                _section_payload(None, name="No id"),
                _section_payload(_SECTION_ID, name="Has id"),
            )
        )

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert [row.name for row in answer.sections] == ["Has id"]

    @pytest.mark.usefixtures("notebook_groups")
    async def test_a_cap_on_either_listing_marks_the_whole_answer_capped(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=_page(
                _section_payload(_SECTION_ID, name="First"),
                _section_payload(_OTHER_SECTION_ID, name="Second"),
            )
        )

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=1)

        assert [row.name for row in answer.sections] == ["First"]
        assert answer.capped is True

    @pytest.mark.usefixtures("notebook_sections", "notebook_groups")
    async def test_two_empty_listings_answer_empty_lists_and_uncapped(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert answer.sections == []
        assert answer.section_groups == []
        assert answer.capped is False


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "parent",
        [
            "Planning",
            "https://onenote.example.invalid/notebooks/team",
            _NOTEBOOK_ID,
            "onenote:///notebooks/",
            OnenoteSectionHandle(_SECTION_ID).uri,
            OnenotePageHandle("0-SYNTHETICPAGE0001!0001").uri,
        ],
    )
    async def test_a_value_that_is_neither_handle_never_reaches_graph(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        parent: str,
    ) -> None:
        with pytest.raises(ToolError):
            _ = await lister.list_sections(client, parent=parent, limit=50)

        assert len(graph.calls) == 0

    async def test_the_refusal_names_both_shapes_and_where_each_comes_from(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_notebooks") as excinfo:
            _ = await lister.list_sections(client, parent="Planning", limit=50)

        message = str(excinfo.value)
        assert "onenote_find_notebook_from_url" in message
        assert "onenote_create_notebook" in message
        assert "onenote_list_sections" in message
        assert "onenote_create_section_group" in message


class TestGraphFailures:
    def test_the_permission_is_notes_read(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Notes.Read",)

    async def test_a_403_on_the_sections_route_is_a_forbidden(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

    async def test_a_404_for_a_stale_notebook_handle_is_a_not_found(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

    async def test_a_404_for_a_stale_group_handle_is_a_not_found(
        self, client: GraphServiceClient, group_sections: respx.Route
    ) -> None:
        group_sections.mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.list_sections(client, parent=_GROUP, limit=50)

    def test_the_not_found_advice_covers_both_shapes(self) -> None:
        assert "onenote_list_notebooks" in lister.GRAPH_NOT_FOUND
        assert "onenote_list_sections" in lister.GRAPH_NOT_FOUND
        assert "fails" in lister.GRAPH_NOT_FOUND
