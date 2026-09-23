import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.tools import onenote_list_notebooks as lister

from .conftest import GRAPH_V1

_NOTEBOOKS = "/me/onenote/notebooks"
_SECTIONS = "/me/onenote/sections"
_SECTION_GROUPS = "/me/onenote/sectionGroups"

_NOTEBOOK_SELECT = (
    "id,displayName,isDefault,isShared,userRole,createdDateTime,lastModifiedDateTime,links"
)
_SECTION_SELECT = "id,displayName,isDefault,lastModifiedDateTime,links"
_SECTION_GROUP_SELECT = "id,displayName"
_HIERARCHY_EXPAND = "parentNotebook,parentSectionGroup"

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


def _notebook_payload(
    notebook_id: str | None,
    *,
    display_name: str | None = "Engineering",
    is_default: bool | None = True,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
    created: str | None = "2026-01-01T00:00:00Z",
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
        "lastModifiedDateTime": modified,
        "links": None if web_url is None else {"oneNoteWebUrl": {"href": web_url}},
    }


def _section_payload(
    section_id: str | None,
    *,
    display_name: str | None = "Standups",
    is_default: bool | None = False,
    modified: str | None = "2026-02-10T00:00:00Z",
    web_url: str | None = "https://onenote.invalid/sections/standups",
    notebook_id: str | None = _ENGINEERING,
    group_id: str | None = None,
) -> dict[str, object]:
    return {
        "id": section_id,
        "displayName": display_name,
        "isDefault": is_default,
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
        monkeypatch.setattr(lister, "MAX_SECTIONS", 3)
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
        monkeypatch.setattr(lister, "MAX_SECTIONS", 3)
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
