import json
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteOwner,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
    onenote_notebook_handle,
    onenote_section_group_handle,
    onenote_section_handle,
)
from office_365_mcp.shared.notes import ContainerOrderBy
from office_365_mcp.shared.seam import Advised
from office_365_mcp.tools import onenote_list_notebooks as lister

from .conftest import GRAPH_V1

_NOTEBOOKS = "/me/onenote/notebooks"
_SECTIONS = "/me/onenote/sections"
_SECTION_GROUPS = "/me/onenote/sectionGroups"

_GROUP = "3f8c1a52-7d4e-4b9a-9c31-0e6f2a8b7d14"
_GROUP_NOTEBOOKS = f"/groups/{_GROUP}/onenote/notebooks"
_GROUP_SECTIONS = f"/groups/{_GROUP}/onenote/sections"
_GROUP_SECTION_GROUPS = f"/groups/{_GROUP}/onenote/sectionGroups"

_SITE = (
    "contoso.sharepoint.invalid,0d1e2f3a-0000-4000-8000-000000000001,"
    + "4b5c6d7e-0000-4000-8000-000000000002"
)
_SITE_NOTEBOOKS = f"/sites/{_SITE}/onenote/notebooks"
_SITE_SECTIONS = f"/sites/{_SITE}/onenote/sections"
_SITE_SECTION_GROUPS = f"/sites/{_SITE}/onenote/sectionGroups"

_NOTEBOOK_SELECT = (
    "id,displayName,isDefault,isShared,userRole,createdBy,createdDateTime,"
    + "lastModifiedDateTime,links"
)
_SECTION_SELECT = "id,displayName,isDefault,createdBy,createdDateTime,lastModifiedDateTime,links"
_SECTION_GROUP_SELECT = "id,displayName"
_HIERARCHY_EXPAND = "parentNotebook,parentSectionGroup"

_ORDERS = (
    "name_asc",
    "name_desc",
    "created_desc",
    "created_asc",
    "last_modified_desc",
    "last_modified_asc",
)

_ENGINEERING = "1-SYNTHETICENGINEERING000000000000000000!100"
_PERSONAL = "1-SYNTHETICPERSONAL0000000000000000000000!100"

_STANDUPS = "1-SYNTHETICSTANDUPS00000000000000000000!101"
_ROADMAP = "1-SYNTHETICROADMAP000000000000000000000!102"
_ORPHANED = "1-SYNTHETICORPHANED000000000000000000000!103"

_OUTER_GROUP = "1-SYNTHETICOUTERGROUP00000000000000000!200"
_INNER_GROUP = "1-SYNTHETICINNERGROUP00000000000000000!201"
_CYCLE_A = "1-SYNTHETICCYCLEA0000000000000000000000!202"
_CYCLE_B = "1-SYNTHETICCYCLEB0000000000000000000000!203"
_MISSING_PARENT = "1-SYNTHETICMISSINGPARENT0000000000000!204"

_SECTION_ONE = "1-SYNTHETICSECTIONONE00000000000000000!301"
_SECTION_TWO = "1-SYNTHETICSECTIONTWO00000000000000000!302"
_SECTION_THREE = "1-SYNTHETICSECTIONTHREE0000000000000000!303"
_SECTION_FOUR = "1-SYNTHETICSECTIONFOUR00000000000000000!304"


def _creator(name: str | None) -> dict[str, object] | None:
    return None if name is None else {"user": {"displayName": name}}


def _notebook_payload(
    notebook_id: str | None,
    *,
    display_name: str | None = "Engineering",
    is_default: bool | None = True,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
    created: str | None = "2026-01-01T00:00:00Z",
    created_by: str | None = None,
    modified: str | None = "2026-02-01T00:00:00Z",
    web_url: str | None = "https://onenote.invalid/notebooks/engineering",
) -> dict[str, object]:
    return {
        "id": notebook_id,
        "displayName": display_name,
        "isDefault": is_default,
        "isShared": is_shared,
        "userRole": user_role,
        "createdDateTime": created,
        "createdBy": _creator(created_by),
        "lastModifiedDateTime": modified,
        "links": None if web_url is None else {"oneNoteWebUrl": {"href": web_url}},
    }


def _section_payload(
    section_id: str | None,
    *,
    display_name: str | None = "Standups",
    is_default: bool | None = False,
    created: str | None = "2026-01-05T00:00:00Z",
    created_by: str | None = None,
    modified: str | None = "2026-02-10T00:00:00Z",
    web_url: str | None = "https://onenote.invalid/sections/standups",
    notebook_id: str | None = _ENGINEERING,
    group_id: str | None = None,
) -> dict[str, object]:
    return {
        "id": section_id,
        "displayName": display_name,
        "isDefault": is_default,
        "createdDateTime": created,
        "createdBy": _creator(created_by),
        "lastModifiedDateTime": modified,
        "links": None if web_url is None else {"oneNoteWebUrl": {"href": web_url}},
        "parentNotebook": None if notebook_id is None else {"id": notebook_id},
        "parentSectionGroup": None if group_id is None else {"id": group_id},
    }


def _group_payload(
    group_id: str, *, display_name: str | None = "Projects", parent_group_id: str | None = None
) -> dict[str, object]:
    return {
        "id": group_id,
        "displayName": display_name,
        "parentSectionGroup": None if parent_group_id is None else {"id": parent_group_id},
    }


def _page(*items: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(items)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


@pytest.fixture
def notebooks_route(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_NOTEBOOKS).mock(return_value=_page(_notebook_payload(_ENGINEERING)))


@pytest.fixture
def sections_route(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SECTIONS).mock(return_value=_page())


@pytest.fixture
def groups_route(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SECTION_GROUPS).mock(return_value=_page())


@pytest.fixture
def group_notebooks_route(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_GROUP_NOTEBOOKS).mock(return_value=_page(_notebook_payload(_ENGINEERING)))


@pytest.fixture
def group_sections_route(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_GROUP_SECTIONS).mock(
        return_value=_page(_section_payload(_STANDUPS, group_id=_OUTER_GROUP))
    )


@pytest.fixture
def group_section_groups_route(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_GROUP_SECTION_GROUPS).mock(return_value=_page(_group_payload(_OUTER_GROUP)))


@pytest.fixture
def site_notebooks_route(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SITE_NOTEBOOKS).mock(return_value=_page(_notebook_payload(_ENGINEERING)))


@pytest.fixture
def site_sections_route(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SITE_SECTIONS).mock(
        return_value=_page(_section_payload(_STANDUPS, group_id=_OUTER_GROUP))
    )


@pytest.fixture
def site_section_groups_route(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SITE_SECTION_GROUPS).mock(return_value=_page(_group_payload(_OUTER_GROUP)))


class TestWhatItAsks:
    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_notebooks_asks_every_field_and_no_expand(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        _ = await lister.list_notebooks(client)

        params = notebooks_route.calls.last.request.url.params
        assert params["$select"] == _NOTEBOOK_SELECT
        assert "$expand" not in params
        assert "$filter" not in params
        assert "$orderby" not in params

    @pytest.mark.usefixtures("notebooks_route", "groups_route")
    async def test_sections_asks_every_field_and_both_parents(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        _ = await lister.list_notebooks(client)

        params = sections_route.calls.last.request.url.params
        assert params["$select"] == _SECTION_SELECT
        assert params["$expand"] == _HIERARCHY_EXPAND

    @pytest.mark.usefixtures("notebooks_route", "sections_route")
    async def test_section_groups_asks_id_and_name_and_both_parents(
        self, client: GraphServiceClient, groups_route: respx.Route
    ) -> None:
        _ = await lister.list_notebooks(client)

        params = groups_route.calls.last.request.url.params
        assert params["$select"] == _SECTION_GROUP_SELECT
        assert params["$expand"] == _HIERARCHY_EXPAND

    async def test_it_calls_each_endpoint_exactly_once(
        self,
        client: GraphServiceClient,
        notebooks_route: respx.Route,
        sections_route: respx.Route,
        groups_route: respx.Route,
    ) -> None:
        _ = await lister.list_notebooks(client)

        assert notebooks_route.call_count == 1
        assert sections_route.call_count == 1
        assert groups_route.call_count == 1

    @pytest.mark.usefixtures("notebooks_route", "groups_route")
    async def test_the_sections_collection_is_paged_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_SECTIONS, params={"$skiptoken": "second"}).mock(
            return_value=_page(_section_payload(_ROADMAP, display_name="Roadmap"))
        )
        graph.get(_SECTIONS).mock(
            return_value=_page(
                _section_payload(_STANDUPS, display_name="Standups"),
                next_link=f"{GRAPH_V1}{_SECTIONS}?$skiptoken=second",
            )
        )

        result = await lister.list_notebooks(client)

        names = {section.name for section in result.notebooks[0].sections}
        assert names == {"Roadmap", "Standups"}

    def test_the_startup_probe_calls_this_tool_with_no_arguments_at_all(self) -> None:
        assert lister.GRAPH_CALL_EXAMPLE == {}

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Notes.Read",)


class TestWhatItAnswers:
    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_notebook_with_no_sections_answers_an_empty_list(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(return_value=_page())

        result = await lister.list_notebooks(client)

        assert len(result.notebooks) == 1
        assert result.notebooks[0].sections == []

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_section_at_the_notebooks_top_level_has_no_group_path(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(_STANDUPS, group_id=None)))

        result = await lister.list_notebooks(client)

        section = result.notebooks[0].sections[0]
        assert section.group_path is None

    @pytest.mark.usefixtures("notebooks_route")
    async def test_a_section_nested_two_groups_deep_joins_outermost_first(
        self,
        client: GraphServiceClient,
        sections_route: respx.Route,
        groups_route: respx.Route,
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(_STANDUPS, group_id=_INNER_GROUP)))
        groups_route.mock(
            return_value=_page(
                _group_payload(_OUTER_GROUP, display_name="Projects", parent_group_id=None),
                _group_payload(_INNER_GROUP, display_name="2026", parent_group_id=_OUTER_GROUP),
            )
        )

        result = await lister.list_notebooks(client)

        section = result.notebooks[0].sections[0]
        assert section.group_path == "Projects / 2026"

    @pytest.mark.usefixtures("notebooks_route")
    async def test_a_cycle_between_two_groups_terminates(
        self,
        client: GraphServiceClient,
        sections_route: respx.Route,
        groups_route: respx.Route,
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(_STANDUPS, group_id=_CYCLE_A)))
        groups_route.mock(
            return_value=_page(
                _group_payload(_CYCLE_A, display_name="A", parent_group_id=_CYCLE_B),
                _group_payload(_CYCLE_B, display_name="B", parent_group_id=_CYCLE_A),
            )
        )

        result = await lister.list_notebooks(client)

        section = result.notebooks[0].sections[0]
        assert section.group_path == "B / A"

    @pytest.mark.usefixtures("notebooks_route")
    async def test_a_group_whose_parent_is_unknown_stops_there(
        self,
        client: GraphServiceClient,
        sections_route: respx.Route,
        groups_route: respx.Route,
    ) -> None:
        sections_route.mock(
            return_value=_page(_section_payload(_STANDUPS, group_id=_MISSING_PARENT))
        )
        groups_route.mock(
            return_value=_page(
                _group_payload(_MISSING_PARENT, display_name="Orphaned", parent_group_id=_ORPHANED)
            )
        )

        result = await lister.list_notebooks(client)

        section = result.notebooks[0].sections[0]
        assert section.group_path == "Orphaned"

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_section_whose_notebook_is_missing_is_dropped(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(
            return_value=_page(
                _section_payload(_STANDUPS, notebook_id="1-SYNTHETICUNKNOWNNOTEBOOK00000!999")
            )
        )

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].sections == []

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_section_with_no_id_is_dropped(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(None)))

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].sections == []

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_section_handle_matches_what_onenote_list_pages_expects(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(_STANDUPS)))

        result = await lister.list_notebooks(client)

        section = result.notebooks[0].sections[0]
        assert section.uri == OnenoteSectionHandle(_STANDUPS).uri

    @pytest.mark.usefixtures("sections_route", "groups_route")
    @pytest.mark.parametrize(
        ("user_role", "expected"),
        [
            ("Owner", "Owner"),
            ("Contributor", "Contributor"),
            ("Reader", "Reader"),
            ("None", "None"),
        ],
    )
    async def test_user_role_is_read_off_the_enum(
        self,
        client: GraphServiceClient,
        notebooks_route: respx.Route,
        user_role: str,
        expected: str,
    ) -> None:
        notebooks_route.mock(
            return_value=_page(_notebook_payload(_ENGINEERING, user_role=user_role))
        )

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].user_role == expected

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_user_role_is_null_when_graph_named_none(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        notebooks_route.mock(return_value=_page(_notebook_payload(_ENGINEERING, user_role=None)))

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].user_role is None

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_a_notebooks_links_become_its_web_url(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        notebooks_route.mock(
            return_value=_page(
                _notebook_payload(_ENGINEERING, web_url="https://onenote.invalid/notebooks/eng")
            )
        )

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].web_url == "https://onenote.invalid/notebooks/eng"

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_sections_links_become_its_web_url(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(
            return_value=_page(
                _section_payload(_STANDUPS, web_url="https://onenote.invalid/sections/standups-2")
            )
        )

        result = await lister.list_notebooks(client)

        section = result.notebooks[0].sections[0]
        assert section.web_url == "https://onenote.invalid/sections/standups-2"

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_no_notebooks_answers_an_empty_list(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        notebooks_route.mock(return_value=_page())

        result = await lister.list_notebooks(client)

        assert result.notebooks == []

    @pytest.mark.usefixtures("groups_route")
    async def test_two_notebooks_each_keep_only_their_own_sections(
        self,
        client: GraphServiceClient,
        notebooks_route: respx.Route,
        sections_route: respx.Route,
    ) -> None:
        notebooks_route.mock(
            return_value=_page(
                _notebook_payload(_ENGINEERING, display_name="Engineering"),
                _notebook_payload(_PERSONAL, display_name="Personal"),
            )
        )
        sections_route.mock(
            return_value=_page(
                _section_payload(_STANDUPS, display_name="Standups", notebook_id=_ENGINEERING),
                _section_payload(_ROADMAP, display_name="Journal", notebook_id=_PERSONAL),
            )
        )

        result = await lister.list_notebooks(client)

        by_name = {notebook.name: notebook for notebook in result.notebooks}
        assert [s.name for s in by_name["Engineering"].sections] == ["Standups"]
        assert [s.name for s in by_name["Personal"].sections] == ["Journal"]

    @pytest.mark.usefixtures("notebooks_route", "sections_route", "groups_route")
    async def test_a_short_listing_answers_capped_false(self, client: GraphServiceClient) -> None:
        result = await lister.list_notebooks(client)

        assert result.capped is False

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_sections_collection_at_the_cap_answers_capped_false(
        self,
        client: GraphServiceClient,
        sections_route: respx.Route,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 3)
        sections_route.mock(
            return_value=_page(
                _section_payload(_SECTION_ONE, display_name="One"),
                _section_payload(_SECTION_TWO, display_name="Two"),
                _section_payload(_SECTION_THREE, display_name="Three"),
            )
        )

        result = await lister.list_notebooks(client)

        assert result.capped is False
        assert {s.name for s in result.notebooks[0].sections} == {"One", "Two", "Three"}

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_sections_collection_past_the_cap_answers_capped_true(
        self,
        client: GraphServiceClient,
        sections_route: respx.Route,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 3)
        sections_route.mock(
            return_value=_page(
                _section_payload(_SECTION_ONE, display_name="One"),
                _section_payload(_SECTION_TWO, display_name="Two"),
                _section_payload(_SECTION_THREE, display_name="Three"),
                _section_payload(_SECTION_FOUR, display_name="Four"),
            )
        )

        result = await lister.list_notebooks(client)

        assert result.capped is True
        assert {s.name for s in result.notebooks[0].sections} == {"One", "Two", "Three"}


class TestGraphFailures:
    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        notebooks_route.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.list_notebooks(client)


class TestTheNotebookFilter:
    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_name_contains_becomes_a_lowercase_contains_filter(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        _ = await lister.list_notebooks(client, name_contains="Eng")

        params = notebooks_route.calls.last.request.url.params
        assert params["$filter"] == "contains(tolower(displayName),'eng')"

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_shared_true_becomes_an_is_shared_filter(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        _ = await lister.list_notebooks(client, shared=True)

        assert notebooks_route.calls.last.request.url.params["$filter"] == "isShared eq true"

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_shared_false_becomes_an_is_shared_filter(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        _ = await lister.list_notebooks(client, shared=False)

        assert notebooks_route.calls.last.request.url.params["$filter"] == "isShared eq false"

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_role_becomes_a_userrole_filter(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        _ = await lister.list_notebooks(client, role="Owner")

        assert notebooks_route.calls.last.request.url.params["$filter"] == "userRole eq 'Owner'"

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_all_three_clauses_are_joined_with_and(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        _ = await lister.list_notebooks(
            client, name_contains="Eng", shared=True, role="Contributor"
        )

        assert notebooks_route.calls.last.request.url.params["$filter"] == (
            "contains(tolower(displayName),'eng') and isShared eq true and "
            + "userRole eq 'Contributor'"
        )

    @pytest.mark.usefixtures("sections_route", "groups_route")
    @pytest.mark.usefixtures("notebooks_route")
    async def test_the_filter_never_reaches_the_sections_or_groups_calls(
        self,
        client: GraphServiceClient,
        sections_route: respx.Route,
        groups_route: respx.Route,
    ) -> None:
        _ = await lister.list_notebooks(client, name_contains="Eng", shared=True, role="Owner")

        assert "$filter" not in sections_route.calls.last.request.url.params
        assert "$filter" not in groups_route.calls.last.request.url.params

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_no_arguments_send_no_filter(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        _ = await lister.list_notebooks(client)

        assert "$filter" not in notebooks_route.calls.last.request.url.params


class TestNotebookAndSectionGroupHandles:
    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_a_notebook_carries_its_own_handle(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        notebooks_route.mock(return_value=_page(_notebook_payload(_ENGINEERING)))

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].uri == OnenoteNotebookHandle(_ENGINEERING).uri

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_a_notebook_with_no_id_is_dropped(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        notebooks_route.mock(
            return_value=_page(
                _notebook_payload(None, display_name="No id"),
                _notebook_payload(_ENGINEERING, display_name="Has id"),
            )
        )

        result = await lister.list_notebooks(client)

        assert [notebook.name for notebook in result.notebooks] == ["Has id"]

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_section_directly_under_its_notebook_has_no_group_uri(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(_STANDUPS, group_id=None)))

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].sections[0].group_uri is None

    @pytest.mark.usefixtures("notebooks_route")
    async def test_a_section_inside_a_group_carries_that_groups_handle(
        self,
        client: GraphServiceClient,
        sections_route: respx.Route,
        groups_route: respx.Route,
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(_STANDUPS, group_id=_OUTER_GROUP)))
        groups_route.mock(return_value=_page(_group_payload(_OUTER_GROUP)))

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].sections[0].group_uri == (
            OnenoteSectionGroupHandle(_OUTER_GROUP).uri
        )


class TestTheCreationTime:
    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_section_reports_when_it_was_created(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(_STANDUPS)))

        result = await lister.list_notebooks(client)

        created_at = result.notebooks[0].sections[0].created_at
        assert created_at is not None
        assert created_at.isoformat() == "2026-01-05T00:00:00+00:00"

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_section_with_no_creation_time_reports_null(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(_STANDUPS, created=None)))

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].sections[0].created_at is None


class TestTheCreator:
    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_a_notebook_reports_the_display_name_of_its_creator(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        notebooks_route.mock(
            return_value=_page(_notebook_payload(_ENGINEERING, created_by="Ada Lovelace"))
        )

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].created_by == "Ada Lovelace"

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_a_notebook_with_no_creator_reports_null(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        notebooks_route.mock(return_value=_page(_notebook_payload(_ENGINEERING, created_by=None)))

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].created_by is None

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_a_notebook_made_by_an_application_reports_null(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        payload = _notebook_payload(_ENGINEERING)
        payload["createdBy"] = {"application": {"displayName": "Import Bot"}}
        notebooks_route.mock(return_value=_page(payload))

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].created_by is None

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_section_reports_the_display_name_of_its_creator(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(
            return_value=_page(_section_payload(_STANDUPS, created_by="Grace Hopper"))
        )

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].sections[0].created_by == "Grace Hopper"

    @pytest.mark.usefixtures("groups_route", "notebooks_route")
    async def test_a_section_with_no_creator_reports_null(
        self, client: GraphServiceClient, sections_route: respx.Route
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(_STANDUPS, created_by=None)))

        result = await lister.list_notebooks(client)

        assert result.notebooks[0].sections[0].created_by is None


class TestTheCreatorFilter:
    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_created_by_keeps_a_match_whatever_the_case(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        notebooks_route.mock(
            return_value=_page(
                _notebook_payload(_ENGINEERING, display_name="Mine", created_by="Ada Lovelace"),
                _notebook_payload(_PERSONAL, display_name="Theirs", created_by="Grace Hopper"),
            )
        )

        result = await lister.list_notebooks(client, created_by="LOVELACE")

        assert [notebook.name for notebook in result.notebooks] == ["Mine"]

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_created_by_leaves_out_a_notebook_with_no_creator(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        notebooks_route.mock(
            return_value=_page(
                _notebook_payload(_ENGINEERING, display_name="Named", created_by="Ada Lovelace"),
                _notebook_payload(_PERSONAL, display_name="Nameless", created_by=None),
            )
        )

        result = await lister.list_notebooks(client, created_by="a")

        assert [notebook.name for notebook in result.notebooks] == ["Named"]

    @pytest.mark.usefixtures("groups_route")
    async def test_a_kept_notebook_keeps_every_section_whoever_made_it(
        self,
        client: GraphServiceClient,
        notebooks_route: respx.Route,
        sections_route: respx.Route,
    ) -> None:
        notebooks_route.mock(
            return_value=_page(_notebook_payload(_ENGINEERING, created_by="Ada Lovelace"))
        )
        sections_route.mock(
            return_value=_page(
                _section_payload(_STANDUPS, display_name="By Ada", created_by="Ada Lovelace"),
                _section_payload(_ROADMAP, display_name="By Grace", created_by="Grace Hopper"),
                _section_payload(_SECTION_ONE, display_name="By nobody", created_by=None),
            )
        )

        result = await lister.list_notebooks(client, created_by="ada")

        assert [s.name for s in result.notebooks[0].sections] == ["By Ada", "By Grace", "By nobody"]

    @pytest.mark.usefixtures("groups_route")
    async def test_the_sections_of_a_notebook_it_left_out_are_not_listed(
        self,
        client: GraphServiceClient,
        notebooks_route: respx.Route,
        sections_route: respx.Route,
    ) -> None:
        notebooks_route.mock(
            return_value=_page(
                _notebook_payload(_ENGINEERING, created_by="Ada Lovelace"),
                _notebook_payload(_PERSONAL, created_by="Grace Hopper"),
            )
        )
        sections_route.mock(
            return_value=_page(
                _section_payload(_STANDUPS, notebook_id=_ENGINEERING),
                _section_payload(_ROADMAP, notebook_id=_PERSONAL),
            )
        )

        result = await lister.list_notebooks(client, created_by="grace")

        assert [notebook.uri for notebook in result.notebooks] == [
            OnenoteNotebookHandle(_PERSONAL).uri
        ]
        assert [s.uri for s in result.notebooks[0].sections] == [OnenoteSectionHandle(_ROADMAP).uri]

    @pytest.mark.usefixtures("groups_route", "sections_route")
    async def test_created_by_reads_past_the_first_page_of_notebooks(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_NOTEBOOKS, params={"$skiptoken": "second"}).mock(
            return_value=_page(_notebook_payload(_PERSONAL, display_name="Late", created_by="Ada"))
        )
        graph.get(_NOTEBOOKS).mock(
            return_value=_page(
                _notebook_payload(_ENGINEERING, display_name="Early", created_by="Grace"),
                next_link=f"{GRAPH_V1}{_NOTEBOOKS}?$skiptoken=second",
            )
        )

        result = await lister.list_notebooks(client, created_by="ada")

        assert [notebook.name for notebook in result.notebooks] == ["Late"]

    async def test_created_by_sends_no_filter_and_no_extra_request(
        self,
        client: GraphServiceClient,
        notebooks_route: respx.Route,
        sections_route: respx.Route,
        groups_route: respx.Route,
    ) -> None:
        _ = await lister.list_notebooks(client, created_by="ada")

        assert "$filter" not in notebooks_route.calls.last.request.url.params
        assert "$filter" not in sections_route.calls.last.request.url.params
        assert "$filter" not in groups_route.calls.last.request.url.params
        assert notebooks_route.call_count == 1
        assert sections_route.call_count == 1
        assert groups_route.call_count == 1

    @pytest.mark.usefixtures("sections_route", "groups_route")
    async def test_created_by_joins_the_server_side_filters_without_adding_a_clause(
        self, client: GraphServiceClient, notebooks_route: respx.Route
    ) -> None:
        _ = await lister.list_notebooks(client, name_contains="Eng", created_by="ada", shared=True)

        assert notebooks_route.calls.last.request.url.params["$filter"] == (
            "contains(tolower(displayName),'eng') and isShared eq true"
        )


class TestTheOrder:
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
    async def test_order_by_becomes_the_matching_orderby_on_notebooks_and_sections(
        self,
        client: GraphServiceClient,
        notebooks_route: respx.Route,
        sections_route: respx.Route,
        groups_route: respx.Route,
        order_by: ContainerOrderBy,
        clause: str,
    ) -> None:
        _ = await lister.list_notebooks(client, order_by=order_by)

        assert notebooks_route.calls.last.request.url.params["$orderby"] == clause
        assert sections_route.calls.last.request.url.params["$orderby"] == clause
        assert "$orderby" not in groups_route.calls.last.request.url.params

    async def test_no_order_by_sends_no_orderby_on_any_call(
        self,
        client: GraphServiceClient,
        notebooks_route: respx.Route,
        sections_route: respx.Route,
        groups_route: respx.Route,
    ) -> None:
        _ = await lister.list_notebooks(client)

        assert "$orderby" not in notebooks_route.calls.last.request.url.params
        assert "$orderby" not in sections_route.calls.last.request.url.params
        assert "$orderby" not in groups_route.calls.last.request.url.params

    @pytest.mark.usefixtures("groups_route")
    async def test_the_sections_of_each_notebook_keep_the_order_graph_listed_them_in(
        self,
        client: GraphServiceClient,
        notebooks_route: respx.Route,
        sections_route: respx.Route,
    ) -> None:
        notebooks_route.mock(
            return_value=_page(
                _notebook_payload(_PERSONAL, display_name="Personal"),
                _notebook_payload(_ENGINEERING, display_name="Engineering"),
            )
        )
        sections_route.mock(
            return_value=_page(
                _section_payload(_SECTION_ONE, display_name="Zulu", notebook_id=_ENGINEERING),
                _section_payload(_SECTION_TWO, display_name="Yankee", notebook_id=_PERSONAL),
                _section_payload(_SECTION_THREE, display_name="Alpha", notebook_id=_ENGINEERING),
            )
        )

        result = await lister.list_notebooks(client, order_by="name_desc")

        assert [notebook.name for notebook in result.notebooks] == ["Personal", "Engineering"]
        assert [s.name for s in result.notebooks[1].sections] == ["Zulu", "Alpha"]


class TestAGroupsNotebooks:
    async def test_group_sends_each_of_the_three_requests_to_that_groups_route(
        self,
        client: GraphServiceClient,
        group_notebooks_route: respx.Route,
        group_sections_route: respx.Route,
        group_section_groups_route: respx.Route,
    ) -> None:
        _ = await lister.list_notebooks(client, group=_GROUP)

        assert group_notebooks_route.call_count == 1
        assert group_sections_route.call_count == 1
        assert group_section_groups_route.call_count == 1

    @pytest.mark.usefixtures("group_section_groups_route")
    async def test_group_never_calls_the_signed_in_users_own_route(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        group_notebooks_route: respx.Route,
        group_sections_route: respx.Route,
    ) -> None:
        own = graph.get(url__regex=r".*/me/onenote/.*").mock(return_value=_page())

        _ = await lister.list_notebooks(client, group=_GROUP)

        assert own.call_count == 0
        assert group_notebooks_route.call_count == 1
        assert group_sections_route.call_count == 1

    @pytest.mark.usefixtures("groups_route")
    async def test_no_group_keeps_the_signed_in_users_own_routes_and_handles(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        notebooks_route: respx.Route,
        sections_route: respx.Route,
    ) -> None:
        sections_route.mock(return_value=_page(_section_payload(_STANDUPS)))
        grouped = graph.get(url__regex=r".*/groups/.*").mock(return_value=_page())

        result = await lister.list_notebooks(client)

        assert grouped.call_count == 0
        assert notebooks_route.call_count == 1
        assert result.notebooks[0].uri == OnenoteNotebookHandle(_ENGINEERING).uri
        assert result.notebooks[0].sections[0].uri == OnenoteSectionHandle(_STANDUPS).uri

    async def test_group_sends_the_query_strings_of_the_signed_in_users_own_routes(
        self,
        client: GraphServiceClient,
        notebooks_route: respx.Route,
        sections_route: respx.Route,
        groups_route: respx.Route,
        group_notebooks_route: respx.Route,
        group_sections_route: respx.Route,
        group_section_groups_route: respx.Route,
    ) -> None:
        _ = await lister.list_notebooks(
            client, name_contains="Eng", shared=True, role="Contributor", order_by="name_desc"
        )
        _ = await lister.list_notebooks(
            client,
            group=_GROUP,
            name_contains="Eng",
            shared=True,
            role="Contributor",
            order_by="name_desc",
        )

        for own, grouped in (
            (notebooks_route, group_notebooks_route),
            (sections_route, group_sections_route),
            (groups_route, group_section_groups_route),
        ):
            assert grouped.calls.last.request.url.params == own.calls.last.request.url.params

    async def test_group_sends_the_filter_and_the_order_on_the_group_route(
        self,
        client: GraphServiceClient,
        group_notebooks_route: respx.Route,
        group_sections_route: respx.Route,
        group_section_groups_route: respx.Route,
    ) -> None:
        _ = await lister.list_notebooks(
            client,
            group=_GROUP,
            name_contains="Eng",
            shared=True,
            role="Contributor",
            order_by="name_desc",
        )

        notebook_params = group_notebooks_route.calls.last.request.url.params
        assert notebook_params["$filter"] == (
            "contains(tolower(displayName),'eng') and isShared eq true and "
            + "userRole eq 'Contributor'"
        )
        assert notebook_params["$orderby"] == "displayName desc"
        assert group_sections_route.calls.last.request.url.params["$orderby"] == "displayName desc"
        assert "$filter" not in group_sections_route.calls.last.request.url.params
        assert "$orderby" not in group_section_groups_route.calls.last.request.url.params

    @pytest.mark.usefixtures("group_section_groups_route")
    async def test_group_filters_the_notebooks_by_creator_without_a_filter_clause(
        self,
        client: GraphServiceClient,
        group_notebooks_route: respx.Route,
        group_sections_route: respx.Route,
    ) -> None:
        group_notebooks_route.mock(
            return_value=_page(
                _notebook_payload(_ENGINEERING, display_name="Mine", created_by="Ada Lovelace"),
                _notebook_payload(_PERSONAL, display_name="Theirs", created_by="Grace Hopper"),
            )
        )
        group_sections_route.mock(return_value=_page())

        result = await lister.list_notebooks(client, group=_GROUP, created_by="lovelace")

        assert [notebook.name for notebook in result.notebooks] == ["Mine"]
        assert "$filter" not in group_notebooks_route.calls.last.request.url.params

    @pytest.mark.usefixtures("group_notebooks_route", "group_section_groups_route")
    async def test_group_follows_a_next_link_on_the_group_route(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_GROUP_SECTIONS, params={"$skiptoken": "second"}).mock(
            return_value=_page(_section_payload(_ROADMAP, display_name="Roadmap"))
        )
        graph.get(_GROUP_SECTIONS).mock(
            return_value=_page(
                _section_payload(_STANDUPS, display_name="Standups"),
                next_link=f"{GRAPH_V1}{_GROUP_SECTIONS}?$skiptoken=second",
            )
        )

        result = await lister.list_notebooks(client, group=_GROUP)

        assert {section.name for section in result.notebooks[0].sections} == {
            "Roadmap",
            "Standups",
        }

    @pytest.mark.usefixtures(
        "group_notebooks_route", "group_sections_route", "group_section_groups_route"
    )
    async def test_every_handle_in_a_group_answer_carries_the_group(
        self, client: GraphServiceClient
    ) -> None:
        result = await lister.list_notebooks(client, group=_GROUP)

        notebook = result.notebooks[0]
        section = notebook.sections[0]
        assert section.group_uri is not None
        assert notebook.uri.startswith(f"onenote:///groups/{_GROUP}/notebooks/")
        assert onenote_notebook_handle(notebook.uri) == OnenoteNotebookHandle(
            _ENGINEERING, owner=OnenoteOwner("groups", _GROUP)
        )
        assert onenote_section_handle(section.uri) == OnenoteSectionHandle(
            _STANDUPS, owner=OnenoteOwner("groups", _GROUP)
        )
        assert onenote_section_group_handle(section.group_uri) == OnenoteSectionGroupHandle(
            _OUTER_GROUP, owner=OnenoteOwner("groups", _GROUP)
        )

    async def test_a_group_404_arrives_classified_as_not_found(
        self, client: GraphServiceClient, group_notebooks_route: respx.Route
    ) -> None:
        group_notebooks_route.mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "gone"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.list_notebooks(client, group=_GROUP)


class TestASitesNotebooks:
    async def test_site_sends_each_of_the_three_requests_to_that_sites_route(
        self,
        client: GraphServiceClient,
        site_notebooks_route: respx.Route,
        site_sections_route: respx.Route,
        site_section_groups_route: respx.Route,
    ) -> None:
        _ = await lister.list_notebooks(client, site=_SITE)

        assert site_notebooks_route.call_count == 1
        assert site_sections_route.call_count == 1
        assert site_section_groups_route.call_count == 1

    @pytest.mark.usefixtures(
        "site_notebooks_route", "site_sections_route", "site_section_groups_route"
    )
    async def test_site_never_calls_the_signed_in_users_own_route(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        own = graph.get(url__regex=r".*/me/onenote/.*").mock(return_value=_page())

        _ = await lister.list_notebooks(client, site=_SITE)

        assert own.call_count == 0

    @pytest.mark.usefixtures(
        "site_notebooks_route", "site_sections_route", "site_section_groups_route"
    )
    async def test_every_handle_in_a_site_answer_carries_the_site(
        self, client: GraphServiceClient
    ) -> None:
        result = await lister.list_notebooks(client, site=_SITE)

        notebook = result.notebooks[0]
        section = notebook.sections[0]
        assert section.group_uri is not None
        assert notebook.uri.startswith("onenote:///sites/")
        assert section.uri.startswith("onenote:///sites/")
        assert section.group_uri.startswith("onenote:///sites/")
        assert onenote_notebook_handle(notebook.uri) == OnenoteNotebookHandle(
            _ENGINEERING, owner=OnenoteOwner("sites", _SITE)
        )
        assert onenote_section_handle(section.uri) == OnenoteSectionHandle(
            _STANDUPS, owner=OnenoteOwner("sites", _SITE)
        )
        assert onenote_section_group_handle(section.group_uri) == OnenoteSectionGroupHandle(
            _OUTER_GROUP, owner=OnenoteOwner("sites", _SITE)
        )

    async def test_group_and_site_together_are_refused_before_any_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="takes at most one of `group` and `site`") as raised:
            _ = await lister.list_notebooks(client, group=_GROUP, site=_SITE)

        assert "never to both" in str(raised.value)
        assert "do not retry it as it is" in str(raised.value)
        assert len(graph.calls) == 0

    async def test_a_site_404_arrives_classified_as_not_found(
        self, client: GraphServiceClient, site_notebooks_route: respx.Route
    ) -> None:
        site_notebooks_route.mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "gone"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.list_notebooks(client, site=_SITE)


class TestAnOwnerThatRefusesTheCaller:
    @pytest.mark.parametrize(
        ("group", "site", "path"),
        [(_GROUP, None, _GROUP_NOTEBOOKS), (None, _SITE, _SITE_NOTEBOOKS)],
        ids=["group", "site"],
    )
    async def test_a_403_for_a_named_owner_raises_the_canonical_advice_with_diagnostics(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        group: str | None,
        site: str | None,
        path: str,
    ) -> None:
        _ = graph.get(path).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(Advised) as raised:
            _ = await lister.list_notebooks(client, group=group, site=site)

        message = str(raised.value)
        assert message.startswith(
            "Microsoft 365 refused this request for the `group` or the `site` that this call "
            + "named. Most likely, the signed-in user is not a member of that group or site, or "
            + "the id is wrong."
        )
        assert "grant the delegated permission Notes.Read" in message
        assert (
            "If the user already has access, ask a Microsoft 365 administrator to examine the "
            + "OneNote permissions of this connector."
        ) in message
        assert "are not the problem" not in message
        assert "This same call fails again, so do not retry it." in message
        assert message.endswith("(HTTP 403, Graph error code accessDenied)")


class TestHowItDescribesItself:
    async def _tool(self, transport: httpx.AsyncClient) -> Tool:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)
        tool = await mcp.get_tool(lister.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"
        return tool

    async def _properties(self, transport: httpx.AsyncClient) -> Mapping[str, Mapping[str, object]]:
        tool = await self._tool(transport)
        return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])

    async def test_it_takes_the_group_the_site_and_the_five_narrowing_and_ordering_arguments(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = await self._properties(transport)

        assert set(properties) == {
            "group",
            "site",
            "name_contains",
            "created_by",
            "shared",
            "role",
            "order_by",
        }

    async def test_group_is_optional_and_never_empty(self, transport: httpx.AsyncClient) -> None:
        tool = await self._tool(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])

        assert "group" not in tool.parameters.get("required", [])
        assert cast("list[Mapping[str, object]]", properties["group"]["anyOf"])[0]["minLength"] == 1

    async def test_group_says_whose_notebooks_it_lists_and_where_to_take_its_id(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = await self._properties(transport)

        described = cast("str", properties["group"]["description"])
        assert "whose notebooks this call lists" in described
        assert "A team id is a group id." in described
        assert "Ask the user for it, or copy a team id from an earlier result." in described
        assert "teams_list_my_teams" not in described
        assert "Omit it to list every notebook the user owns" in described

    async def test_site_is_optional_and_never_empty(self, transport: httpx.AsyncClient) -> None:
        tool = await self._tool(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])

        assert "site" not in tool.parameters.get("required", [])
        assert cast("list[Mapping[str, object]]", properties["site"]["anyOf"])[0]["minLength"] == 1

    async def test_site_says_whose_notebooks_it_lists_and_how_its_id_is_spelled(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = await self._properties(transport)

        described = cast("str", properties["site"]["description"])
        assert "The SharePoint site whose notebooks this call lists" in described
        assert "a host name and two ids, joined by commas, and not percent-encoded" in described
        assert "Ask the user for it." in described
        assert "Pass at most one of `group` and `site`." in described

    async def test_the_description_offers_group_and_site_and_drops_the_sharepoint_limit(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await self._tool(transport)

        described = tool.description or ""
        assert (
            "Pass `group` to list the notebooks of one Microsoft 365 group or team instead."
            in described
        )
        assert "Pass `site` to list the notebooks of one SharePoint site instead." in described
        assert "does not reach a notebook on a SharePoint site" not in described
        assert "or in a Microsoft 365 team" not in described

    def test_the_handle_fields_name_the_group_and_site_spellings(self) -> None:
        spelling = (
            "A handle from a group or site notebook starts with onenote:///groups/{group}/ "
            + "or onenote:///sites/{site}/ instead."
        )

        assert spelling in (lister.Notebook.model_fields["uri"].description or "")
        assert spelling in (lister.NotebookSection.model_fields["uri"].description or "")
        assert spelling in (lister.NotebookSection.model_fields["group_uri"].description or "")

    def test_a_not_found_names_the_group_and_where_to_take_its_id(self) -> None:
        advice = lister.GRAPH_NOT_FOUND

        assert "`group`" in advice
        assert (
            "If this call named a `group` or a `site`, the id most likely names nothing that the "
            + "signed-in user can reach. Ask the user for the correct id."
            in advice
        )
        assert "teams_list_my_teams" not in advice
        assert "fails again" in advice

    def test_a_not_found_names_the_site_and_says_the_same_id_fails_again(self) -> None:
        advice = lister.GRAPH_NOT_FOUND

        assert "If this call named a `group` or a `site`, the id most likely names nothing" in (
            advice
        )
        assert "Ask the user for the correct id. This same id fails again, so do not retry it." in (
            advice
        )
        assert "If this call named no `group` and no `site`," in advice

    def test_the_notebooks_answer_names_the_group_and_the_site(self) -> None:
        described = lister.Notebooks.model_fields["notebooks"].description or ""

        assert "With `group` or `site`, these are the notebooks of that group or site." in described

    async def test_order_by_offers_the_six_orders(self, transport: httpx.AsyncClient) -> None:
        properties = await self._properties(transport)

        offered = json.dumps(properties["order_by"])
        for order in _ORDERS:
            assert f'"{order}"' in offered

    async def test_order_by_names_the_default_order(self, transport: httpx.AsyncClient) -> None:
        properties = await self._properties(transport)

        described = cast("str", properties["order_by"]["description"])
        assert "Omit it to keep the default order, ascending by name." in described

    async def test_created_by_says_a_notebook_keeps_every_section(
        self, transport: httpx.AsyncClient
    ) -> None:
        properties = await self._properties(transport)

        described = cast("str", properties["created_by"]["description"])
        assert "every one of its sections" in described
        assert "left out" in described

    def test_the_capped_answer_names_created_by_among_the_notebook_only_narrowing_arguments(
        self,
    ) -> None:
        described = lister.Notebooks.model_fields["capped"].description or ""

        assert "`created_by`" in described
        assert "narrow only the notebook listing" in described
