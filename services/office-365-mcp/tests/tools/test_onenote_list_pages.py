from datetime import UTC, date, datetime

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import OnenotePageHandle, OnenoteSectionHandle
from office_365_mcp.shared.notes import PAGE_EXPANSIONS, PAGE_FIELDS
from office_365_mcp.tools import onenote_list_pages as lister

from .conftest import GRAPH_V1

_SECTION_ID = "0-SYNTHETICSECTION0001!0001"
_OTHER_SECTION_ID = "0-SYNTHETICSECTION0002!0001"

_PAGE_ID = "0-SYNTHETICPAGE00001!0001"
_OTHER_PAGE_ID = "0-SYNTHETICPAGE00002!0001"

_PAGES_PATH = "/me/onenote/pages"
_SECTION_PAGES_PATH = "/me/onenote/sections/0-SYNTHETICSECTION0001%210001/pages"

_SECTION = OnenoteSectionHandle(_SECTION_ID).uri


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
) -> dict[str, object]:
    return {
        "id": page_id,
        "title": title,
        "createdDateTime": created_at,
        "lastModifiedDateTime": last_modified_at,
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

    @pytest.mark.parametrize("limit", [0, lister.MAX_PAGES + 1])
    async def test_a_limit_outside_the_window_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await lister.list_pages(client, limit=limit)


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
