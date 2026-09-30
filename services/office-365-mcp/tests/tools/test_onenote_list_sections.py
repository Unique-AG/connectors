import json
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.shared.notes import ContainerOrderBy
from office_365_mcp.tools import onenote_list_sections as lister

from .conftest import GRAPH_V1

_ORDERS = (
    "name_asc",
    "name_desc",
    "created_desc",
    "created_asc",
    "last_modified_desc",
    "last_modified_asc",
)

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


def _creator(name: str | None) -> dict[str, object] | None:
    return None if name is None else {"user": {"displayName": name}}


def _section_payload(
    section_id: str | None,
    *,
    name: str | None = "Planning",
    is_default: bool | None = True,
    created_by: str | None = None,
    last_modified: str | None = "2026-02-10T14:00:00Z",
    web_url: str | None = "https://onenote.example.invalid/sections/planning",
    notebook_name: str | None = None,
) -> dict[str, object]:
    return {
        "id": section_id,
        "displayName": name,
        "isDefault": is_default,
        "createdBy": _creator(created_by),
        "lastModifiedDateTime": last_modified,
        "links": {"oneNoteWebUrl": {"href": web_url} if web_url is not None else None},
        "parentNotebook": (
            {"id": _NOTEBOOK_ID, "displayName": notebook_name}
            if notebook_name is not None
            else None
        ),
    }


def _group_payload(
    group_id: str | None,
    *,
    name: str | None = "Archive",
    created_by: str | None = None,
    last_modified: str | None = "2026-02-10T14:00:00Z",
) -> dict[str, object]:
    return {
        "id": group_id,
        "displayName": name,
        "createdBy": _creator(created_by),
        "lastModifiedDateTime": last_modified,
    }


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
            "createdBy",
            "lastModifiedDateTime",
            "links",
        ]
        assert params["$top"] == "7"
        assert "$filter" not in params
        assert "$orderby" not in params

    @pytest.mark.usefixtures("notebook_groups", "group_sections", "group_groups")
    async def test_the_notebook_sections_route_expands_the_parent_notebook(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, limit=7)

        params = notebook_sections.calls.last.request.url.params
        assert params["$expand"] == "parentNotebook($select=id,displayName)"

    @pytest.mark.usefixtures("notebook_sections", "notebook_groups", "group_groups")
    async def test_the_group_sections_route_expands_the_parent_notebook(
        self, client: GraphServiceClient, group_sections: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_GROUP, limit=7)

        params = group_sections.calls.last.request.url.params
        assert params["$expand"] == "parentNotebook($select=id,displayName)"

    @pytest.mark.usefixtures("notebook_sections", "group_sections", "group_groups")
    async def test_the_notebook_groups_route_asks_select_and_top(
        self, client: GraphServiceClient, notebook_groups: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, limit=7)

        params = notebook_groups.calls.last.request.url.params
        assert params["$select"].split(",") == [
            "id",
            "displayName",
            "createdBy",
            "lastModifiedDateTime",
        ]
        assert params["$top"] == "7"
        assert "$orderby" not in params

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

    @pytest.mark.usefixtures("notebook_groups")
    async def test_the_notebook_name_is_read_off_a_sections_expansion_at_no_extra_cost(
        self, client: GraphServiceClient, notebook_sections: respx.Route, graph: respx.MockRouter
    ) -> None:
        notebook_sections.mock(
            return_value=_page(_section_payload(_SECTION_ID, notebook_name="Engineering"))
        )

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert answer.notebook_name == "Engineering"
        assert len(graph.calls) == 2

    @pytest.mark.usefixtures("notebook_groups")
    async def test_the_notebook_name_is_null_when_no_section_carries_a_parent_notebook(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(return_value=_page(_section_payload(_SECTION_ID)))

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert answer.notebook_name is None

    @pytest.mark.usefixtures("notebook_sections", "notebook_groups")
    async def test_the_notebook_name_is_null_when_the_section_listing_is_empty(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert answer.notebook_name is None


class TestTheCreator:
    @pytest.mark.usefixtures("notebook_groups")
    async def test_a_section_reports_the_display_name_of_its_creator(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=_page(_section_payload(_SECTION_ID, created_by="Ada Lovelace"))
        )

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert answer.sections[0].created_by == "Ada Lovelace"

    @pytest.mark.usefixtures("notebook_groups")
    async def test_a_section_with_no_creator_reports_null(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(return_value=_page(_section_payload(_SECTION_ID, created_by=None)))

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert answer.sections[0].created_by is None

    @pytest.mark.usefixtures("notebook_sections")
    async def test_a_section_group_reports_the_display_name_of_its_creator(
        self, client: GraphServiceClient, notebook_groups: respx.Route
    ) -> None:
        notebook_groups.mock(
            return_value=_page(_group_payload(_CHILD_GROUP_ID, created_by="Grace Hopper"))
        )

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert answer.section_groups[0].created_by == "Grace Hopper"

    @pytest.mark.usefixtures("notebook_sections")
    async def test_a_section_group_made_by_an_application_reports_null(
        self, client: GraphServiceClient, notebook_groups: respx.Route
    ) -> None:
        payload = _group_payload(_CHILD_GROUP_ID)
        payload["createdBy"] = {"application": {"displayName": "Import Bot"}}
        notebook_groups.mock(return_value=_page(payload))

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert answer.section_groups[0].created_by is None


class TestTheCreatorFilter:
    async def test_created_by_keeps_a_match_in_both_lists_whatever_the_case(
        self,
        client: GraphServiceClient,
        notebook_sections: respx.Route,
        notebook_groups: respx.Route,
    ) -> None:
        notebook_sections.mock(
            return_value=_page(
                _section_payload(_SECTION_ID, name="Mine", created_by="Ada Lovelace"),
                _section_payload(_OTHER_SECTION_ID, name="Theirs", created_by="Grace Hopper"),
            )
        )
        notebook_groups.mock(
            return_value=_page(
                _group_payload(_CHILD_GROUP_ID, name="Mine", created_by="ADA LOVELACE"),
                _group_payload(_GROUP_ID, name="Theirs", created_by="Grace Hopper"),
            )
        )

        answer = await lister.list_sections(
            client, parent=_NOTEBOOK, created_by="lovelace", limit=50
        )

        assert [row.name for row in answer.sections] == ["Mine"]
        assert [row.name for row in answer.section_groups] == ["Mine"]

    async def test_created_by_leaves_out_a_row_with_no_creator(
        self,
        client: GraphServiceClient,
        notebook_sections: respx.Route,
        notebook_groups: respx.Route,
    ) -> None:
        notebook_sections.mock(
            return_value=_page(
                _section_payload(_SECTION_ID, name="Named", created_by="Ada Lovelace"),
                _section_payload(_OTHER_SECTION_ID, name="Nameless", created_by=None),
            )
        )
        notebook_groups.mock(
            return_value=_page(
                _group_payload(_CHILD_GROUP_ID, name="Named", created_by="Ada Lovelace"),
                _group_payload(_GROUP_ID, name="Nameless", created_by=None),
            )
        )

        answer = await lister.list_sections(client, parent=_NOTEBOOK, created_by="a", limit=50)

        assert [row.name for row in answer.sections] == ["Named"]
        assert [row.name for row in answer.section_groups] == ["Named"]

    @pytest.mark.usefixtures("notebook_groups")
    async def test_created_by_asks_for_full_pages_and_not_for_limit_rows(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, created_by="ada", limit=7)

        assert notebook_sections.calls.last.request.url.params["$top"] == str(lister.MAX_SECTIONS)

    @pytest.mark.usefixtures("notebook_sections")
    async def test_created_by_asks_the_section_group_route_for_full_pages_too(
        self, client: GraphServiceClient, notebook_groups: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, created_by="ada", limit=7)

        assert notebook_groups.calls.last.request.url.params["$top"] == str(lister.MAX_SECTIONS)

    async def test_created_by_sends_no_filter_of_its_own(
        self,
        client: GraphServiceClient,
        notebook_sections: respx.Route,
        notebook_groups: respx.Route,
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, created_by="ada", limit=50)

        assert "$filter" not in notebook_sections.calls.last.request.url.params
        assert "$filter" not in notebook_groups.calls.last.request.url.params

    @pytest.mark.usefixtures("notebook_groups")
    async def test_created_by_finds_a_match_past_the_first_limit_rows(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_NOTEBOOK_SECTIONS_PATH, params={"$skiptoken": "second"}).mock(
            return_value=_page(
                _section_payload(_OTHER_SECTION_ID, name="Late", created_by="Ada Lovelace")
            )
        )
        graph.get(_NOTEBOOK_SECTIONS_PATH).mock(
            return_value=_page(
                _section_payload(_SECTION_ID, name="Early", created_by="Grace Hopper"),
                next_link=f"{GRAPH_V1}{_NOTEBOOK_SECTIONS_PATH}?$skiptoken=second",
            )
        )

        answer = await lister.list_sections(client, parent=_NOTEBOOK, created_by="ada", limit=1)

        assert [row.name for row in answer.sections] == ["Late"]
        assert answer.capped is False

    @pytest.mark.usefixtures("notebook_groups")
    async def test_limit_still_bounds_the_rows_kept_when_created_by_is_set(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=_page(
                _section_payload(_SECTION_ID, name="First", created_by="Ada Lovelace"),
                _section_payload(_OTHER_SECTION_ID, name="Second", created_by="Ada Lovelace"),
            )
        )

        answer = await lister.list_sections(client, parent=_NOTEBOOK, created_by="ada", limit=1)

        assert [row.name for row in answer.sections] == ["First"]
        assert answer.capped is True

    @pytest.mark.usefixtures("notebook_groups")
    async def test_the_walk_stops_at_the_scan_cap_and_answers_capped(
        self,
        client: GraphServiceClient,
        notebook_sections: respx.Route,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 2)
        notebook_sections.mock(
            return_value=_page(
                _section_payload(_SECTION_ID, name="One", created_by="Grace Hopper"),
                _section_payload(_OTHER_SECTION_ID, name="Two", created_by="Grace Hopper"),
                _section_payload("0-SYNTHETICSECTION0003!0001", name="Three", created_by="Ada"),
            )
        )

        answer = await lister.list_sections(client, parent=_NOTEBOOK, created_by="ada", limit=50)

        assert answer.sections == []
        assert answer.capped is True

    @pytest.mark.usefixtures("notebook_groups")
    async def test_without_created_by_the_walk_stays_inside_limit(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=_page(
                _section_payload(_SECTION_ID, name="First"),
                _section_payload(_OTHER_SECTION_ID, name="Second"),
                next_link=f"{GRAPH_V1}{_NOTEBOOK_SECTIONS_PATH}?$skiptoken=second",
            )
        )

        answer = await lister.list_sections(client, parent=_NOTEBOOK, limit=1)

        assert [row.name for row in answer.sections] == ["First"]
        assert notebook_sections.call_count == 1


class TestTheOrder:
    @pytest.mark.usefixtures("group_sections", "group_groups")
    @pytest.mark.parametrize(
        ("order_by", "clause"),
        [
            ("name_asc", "displayName asc"),
            ("name_desc", "displayName desc"),
            ("created_desc", "createdDateTime desc"),
            ("created_asc", "createdDateTime asc"),
            ("last_modified_desc", "lastModifiedDateTime desc"),
            ("last_modified_asc", "lastModifiedDateTime asc"),
        ],
    )
    async def test_order_by_becomes_the_matching_orderby_on_both_notebook_routes(
        self,
        client: GraphServiceClient,
        notebook_sections: respx.Route,
        notebook_groups: respx.Route,
        order_by: ContainerOrderBy,
        clause: str,
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, order_by=order_by, limit=50)

        assert notebook_sections.calls.last.request.url.params["$orderby"] == clause
        assert notebook_groups.calls.last.request.url.params["$orderby"] == clause

    @pytest.mark.usefixtures("notebook_sections", "notebook_groups")
    async def test_order_by_reaches_both_group_routes_too(
        self, client: GraphServiceClient, group_sections: respx.Route, group_groups: respx.Route
    ) -> None:
        _ = await lister.list_sections(client, parent=_GROUP, order_by="created_asc", limit=50)

        assert group_sections.calls.last.request.url.params["$orderby"] == "createdDateTime asc"
        assert group_groups.calls.last.request.url.params["$orderby"] == "createdDateTime asc"

    @pytest.mark.usefixtures("group_sections", "group_groups")
    async def test_no_order_by_sends_no_orderby_on_either_notebook_route(
        self,
        client: GraphServiceClient,
        notebook_sections: respx.Route,
        notebook_groups: respx.Route,
    ) -> None:
        _ = await lister.list_sections(client, parent=_NOTEBOOK, limit=50)

        assert "$orderby" not in notebook_sections.calls.last.request.url.params
        assert "$orderby" not in notebook_groups.calls.last.request.url.params

    @pytest.mark.usefixtures("notebook_groups")
    async def test_the_rows_keep_the_order_graph_listed_them_in(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        notebook_sections.mock(
            return_value=_page(
                _section_payload(_SECTION_ID, name="Zulu"),
                _section_payload(_OTHER_SECTION_ID, name="Alpha"),
            )
        )

        answer = await lister.list_sections(
            client, parent=_NOTEBOOK, order_by="name_desc", limit=50
        )

        assert [row.name for row in answer.sections] == ["Zulu", "Alpha"]

    @pytest.mark.usefixtures("notebook_groups")
    async def test_order_by_and_created_by_go_out_together(
        self, client: GraphServiceClient, notebook_sections: respx.Route
    ) -> None:
        _ = await lister.list_sections(
            client, parent=_NOTEBOOK, created_by="ada", order_by="created_desc", limit=7
        )

        params = notebook_sections.calls.last.request.url.params
        assert params["$orderby"] == "createdDateTime desc"
        assert params["$top"] == str(lister.MAX_SECTIONS)


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


class TestHowItDescribesItself:
    def test_it_names_onenote_list_notebooks_as_the_whole_tree_alternative(self) -> None:
        assert "onenote_list_notebooks" in lister._DESCRIPTION  # pyright: ignore[reportPrivateUsage]

    def test_it_states_the_documented_default_order_instead_of_an_unspecified_one(self) -> None:
        assert "ascending" in lister._DESCRIPTION  # pyright: ignore[reportPrivateUsage]
        assert "whatever order" not in lister._DESCRIPTION  # pyright: ignore[reportPrivateUsage]

    def test_the_description_warns_about_the_section_group_403_without_naming_a_write_tool(
        self,
    ) -> None:
        assert "403" in lister._DESCRIPTION  # pyright: ignore[reportPrivateUsage]
        assert "onenote_copy_section" not in lister._DESCRIPTION  # pyright: ignore[reportPrivateUsage]


class TestItsArguments:
    async def _properties(self, transport: httpx.AsyncClient) -> Mapping[str, Mapping[str, object]]:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)
        tool = await mcp.get_tool(lister.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"
        return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])

    async def test_it_takes_the_parent_the_two_narrowing_arguments_the_order_and_the_limit(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = await self._properties(transport)

        assert set(properties) == {"parent", "name_contains", "created_by", "order_by", "limit"}

    async def test_order_by_offers_the_six_orders(self, transport: httpx.AsyncClient) -> None:
        properties = await self._properties(transport)

        offered = json.dumps(properties["order_by"])
        for order in _ORDERS:
            assert f'"{order}"' in offered

    async def test_created_by_says_it_applies_to_both_lists(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = await self._properties(transport)

        described = cast("str", properties["created_by"]["description"])
        assert "both lists" in described
        assert "left out" in described

    def test_the_description_says_order_by_can_replace_the_default_order(self) -> None:
        assert "`order_by`" in lister._DESCRIPTION  # pyright: ignore[reportPrivateUsage]

    def test_no_list_field_promises_only_the_default_order(self) -> None:
        for name in ("sections", "section_groups"):
            described = lister.Sections.model_fields[name].description or ""
            assert "default order" not in described

    def test_the_capped_answer_says_created_by_adds_the_scan_cap(self) -> None:
        described = lister.Sections.model_fields["capped"].description or ""

        assert "`created_by`" in described
        assert str(MAX_SCANNED_ITEMS) in described
        assert "`limit`" in described
