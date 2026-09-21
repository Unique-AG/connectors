from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool, Tool
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import (
    OnenotePageHandle,
    OnenoteSectionHandle,
    onenote_page_handle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm
from office_365_mcp.tools import onenote_create_page as creator
from office_365_mcp.tools.onenote_create_page import CreatedPage, a_person_agrees, create_page

_DEFAULT_ROUTE = "/me/onenote/pages"

_SECTION_ID = "0-EB2FEEF7DCFC3C6B!12345"
_SECTION_URI = OnenoteSectionHandle(_SECTION_ID).uri
_SECTION_ROUTE = "/me/onenote/sections/0-EB2FEEF7DCFC3C6B%2112345/pages"
_SECTION_AUDIENCE_ROUTE = "/me/onenote/sections/0-EB2FEEF7DCFC3C6B%2112345"

_PAGE_ID = "0-EB2FEEF7DCFC3C6B!1-0"

_OTHER_SECTION_ID = "0-AAAAAAAAAAAAAAAA!99999"

_NOTEBOOKS_ROUTE = "/me/onenote/notebooks"

_NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK000000000000000000!100"
_NOTEBOOK_NAME = "Engineering"
_NOTEBOOK_ROUTE = f"/me/onenote/notebooks/{quote(_NOTEBOOK_ID, safe='')}"

_TITLE = "Q4 planning"
_BODY_HTML = "<p>Ship the plan.</p>"

_WEB_URL = "https://onenote.officeapps.live.invalid/0/Q4-planning"
_CLIENT_URL = "onenote:https://d.docs.live.invalid/0/Documents/Q4.one#Q4-planning"
_CREATED_AT = "2026-01-05T08:00:00Z"

_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _page_payload(
    *,
    page_id: str | None = _PAGE_ID,
    title: str | None = _TITLE,
    web_url: str | None = _WEB_URL,
    client_url: str | None = _CLIENT_URL,
    created_at: str | None = _CREATED_AT,
    parent_section_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": page_id,
        "title": title,
        "createdDateTime": created_at,
        "links": {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        },
    }
    if parent_section_id is not None:
        payload["parentSection"] = {"id": parent_section_id}
    return payload


def _creates(graph: respx.MockRouter, path: str, payload: dict[str, object]) -> respx.Route:
    return graph.post(path).mock(return_value=httpx.Response(201, json=payload))


def _notebook_payload(
    *,
    notebook_id: str | None = _NOTEBOOK_ID,
    name: str | None = _NOTEBOOK_NAME,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
) -> dict[str, object]:
    return {
        "id": notebook_id,
        "displayName": name,
        "isShared": is_shared,
        "userRole": user_role,
    }


def _reads_notebook(
    graph: respx.MockRouter,
    *,
    name: str | None = _NOTEBOOK_NAME,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
) -> respx.Route:
    payload = _notebook_payload(name=name, is_shared=is_shared, user_role=user_role)
    return graph.get(_NOTEBOOK_ROUTE).mock(return_value=httpx.Response(200, json=payload))


def _reads_section_parent(graph: respx.MockRouter, notebook_id: str | None) -> respx.Route:
    payload: dict[str, object] = {
        "id": _SECTION_ID,
        "parentNotebook": None if notebook_id is None else {"id": notebook_id},
    }
    return graph.get(_SECTION_AUDIENCE_ROUTE).mock(return_value=httpx.Response(200, json=payload))


def _reads_default_notebooks(graph: respx.MockRouter, *notebooks: dict[str, object]) -> respx.Route:
    return graph.get(_NOTEBOOKS_ROUTE).mock(
        return_value=httpx.Response(200, json={"value": list(notebooks)})
    )


def _no_default_notebook(graph: respx.MockRouter) -> respx.Route:
    return _reads_default_notebooks(graph)


def _own_unshared_section(graph: respx.MockRouter) -> None:
    _ = _reads_section_parent(graph, _NOTEBOOK_ID)
    _ = _reads_notebook(graph, is_shared=False, user_role="Owner")


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "No page was created."


async def _create(client: GraphServiceClient, **overrides: object) -> CreatedPage:
    arguments: dict[str, object] = {"title": _TITLE, "body_html": _BODY_HTML}
    arguments.update(overrides)
    now = cast("Callable[[], datetime]", arguments.pop("now", lambda: _NOW))
    confirm = cast("Confirm", arguments.pop("confirm", _agrees))
    created = await create_page(
        client,
        title=cast("str", arguments["title"]),
        body_html=cast("str", arguments["body_html"]),
        section=cast("str | None", arguments.get("section")),
        section_name=cast("str | None", arguments.get("section_name")),
        now=now,
        confirm=confirm,
    )
    assert isinstance(created, CreatedPage), "this call was answered with a question, not a page"
    return created


def _calls(graph: respx.MockRouter) -> Sequence[Call]:
    return cast("Sequence[Call]", graph.calls)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_posts_to_the_default_route_when_no_section_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client)

        assert route.call_count == 1
        assert route.calls.last.request.method == "POST"

    async def test_it_posts_to_the_section_route_when_a_section_handle_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, None)
        default_route = graph.post(_DEFAULT_ROUTE).mock(return_value=httpx.Response(201))
        route = _creates(graph, _SECTION_ROUTE, _page_payload())

        _ = await _create(client, section=_SECTION_URI)

        assert route.call_count == 1
        assert default_route.call_count == 0

    async def test_the_content_type_is_exactly_text_html(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client)

        assert route.calls.last.request.headers["Content-Type"] == "text/html"

    async def test_it_asks_for_json_back(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client)

        assert route.calls.last.request.headers["Accept"] == "application/json"

    async def test_the_body_bytes_are_exactly_the_envelope_with_an_escaped_title(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client, title='<Q4> & "plans"', body_html="<p>Ship it.</p>")

        assert route.calls.last.request.content == (
            b"<!DOCTYPE html><html><head>"
            b"<title>&lt;Q4&gt; &amp; &quot;plans&quot;</title>"
            b'<meta name="created" content="2026-01-02T03:04:05+00:00" />'
            b"</head><body><p>Ship it.</p></body></html>"
        )

    async def test_body_html_reaches_graph_byte_for_byte_unescaped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())
        written = '<p>Q1 &amp; Q2 &mdash; 100% done. "quoted" <b>bold</b></p>'

        _ = await _create(client, body_html=written)

        sent = route.calls.last.request.content.decode("utf-8")
        assert f"<body>{written}</body>" in sent

    async def test_it_creates_exactly_one_page_per_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        notebooks = _no_default_notebook(graph)
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client)

        assert notebooks.call_count == 1
        assert route.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        route = graph.post(_DEFAULT_ROUTE).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _create(client)

        assert route.call_count == 1


class TestTheSectionItRefuses:
    @pytest.mark.parametrize(
        "section",
        [
            "General",
            "0-EB2FEEF7DCFC3C6B!12345",
            "https://onenote.officeapps.live.invalid/0/General",
            "onenote:///pages/0-EB2FEEF7DCFC3C6B!1-0",
            "onenote:///sections/",
            "   ",
        ],
    )
    async def test_a_value_that_is_not_a_section_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, section: str
    ) -> None:
        default_route = graph.post(_DEFAULT_ROUTE).mock(return_value=httpx.Response(201))
        section_route = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))

        with pytest.raises(ToolError):
            _ = await _create(client, section=section)

        assert default_route.call_count == 0
        assert section_route.call_count == 0

    async def test_the_refusal_names_onenote_list_notebooks(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_notebooks"):
            _ = await _create(client, section="General")


class TestSectionName:
    async def test_section_name_is_sent_as_a_raw_query_parameter(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client, section_name="Planning")

        assert route.calls.last.request.url.params["sectionName"] == "Planning"

    async def test_no_section_name_sends_no_query_parameter_at_all(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client)

        assert route.calls.last.request.url.params == httpx.QueryParams()

    async def test_both_section_and_section_name_are_refused_before_reaching_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        default_route = graph.post(_DEFAULT_ROUTE).mock(return_value=httpx.Response(201))
        section_route = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))

        with pytest.raises(ToolError, match="section_name"):
            _ = await _create(client, section=_SECTION_URI, section_name="Planning")

        assert default_route.call_count == 0
        assert section_route.call_count == 0

    async def test_the_refusal_names_both_arguments_as_alternatives(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="never both") as refused:
            _ = await _create(client, section=_SECTION_URI, section_name="Planning")

        assert "`section`" in str(refused.value)
        assert "`section_name`" in str(refused.value)

    async def test_the_about_digest_uses_section_name_instead_of_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_default_notebooks(graph, _notebook_payload(is_shared=True, user_role="Owner"))
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload())
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _create(client, section_name="Planning", confirm=capturing)

        assert bound[0] == write_state_for("create", "Planning", _TITLE, _BODY_HTML)
        assert bound[0] != write_state_for("create", "default", _TITLE, _BODY_HTML)

    async def test_the_question_names_the_section_name_when_one_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_default_notebooks(graph, _notebook_payload(is_shared=True, user_role="Owner"))
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload())
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, section_name="Q3 planning", confirm=counting)

        assert len(asked) == 1
        assert (
            "? It goes into the section 'Q3 planning', which Microsoft creates in that notebook "
            + "when no section has that name yet. It opens"
        ) in asked[0]

    async def test_the_question_says_nothing_about_a_section_when_none_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_default_notebooks(graph, _notebook_payload(is_shared=True, user_role="Owner"))
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload())
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, confirm=counting)

        assert len(asked) == 1
        assert "into the section" not in asked[0]


class TestWhatItAnswers:
    async def test_the_handle_is_minted_from_the_id_graph_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(page_id=_PAGE_ID))

        answer = await _create(client)

        assert answer.uri == OnenotePageHandle(_PAGE_ID).uri
        handle = onenote_page_handle(answer.uri)
        assert handle is not None
        assert handle.page_id == _PAGE_ID

    async def test_the_title_is_read_off_graph_and_not_echoed_from_the_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(title="Q4 planning (renamed)"))

        answer = await _create(client, title=_TITLE)

        assert answer.title == "Q4 planning (renamed)"

    async def test_the_links_are_read_off_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        answer = await _create(client)

        assert answer.web_url == _WEB_URL
        assert answer.client_url == _CLIENT_URL

    async def test_missing_links_answer_null_rather_than_a_built_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(web_url=None, client_url=None))

        answer = await _create(client)

        assert answer.web_url is None
        assert answer.client_url is None

    async def test_created_at_is_read_off_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(created_at=_CREATED_AT))

        answer = await _create(client)

        assert answer.created_at == datetime.fromisoformat(_CREATED_AT.replace("Z", "+00:00"))

    async def test_section_uri_is_the_handle_this_call_wrote_into(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, None)
        _ = _creates(graph, _SECTION_ROUTE, _page_payload())

        answer = await _create(client, section=_SECTION_URI)

        assert answer.section_uri == _SECTION_URI

    async def test_section_uri_is_none_when_the_default_section_was_used_and_graph_named_none(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        answer = await _create(client)

        assert answer.section_uri is None

    async def test_section_uri_prefers_graphs_own_parent_section_over_the_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, None)
        _ = _creates(graph, _SECTION_ROUTE, _page_payload(parent_section_id=_OTHER_SECTION_ID))

        answer = await _create(client, section=_SECTION_URI)

        assert answer.section_uri == OnenoteSectionHandle(_OTHER_SECTION_ID).uri

    async def test_section_uri_is_read_off_graph_even_for_the_default_section(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(parent_section_id=_OTHER_SECTION_ID))

        answer = await _create(client)

        assert answer.section_uri == OnenoteSectionHandle(_OTHER_SECTION_ID).uri

    async def test_a_201_with_no_id_is_an_invariant_violation(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(page_id=None))

        with pytest.raises(AssertionError):
            _ = await _create(client)


class TestTheFailuresItPassesOn:
    async def test_a_refused_create_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        _ = graph.post(_DEFAULT_ROUTE).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _create(client)

    async def test_a_missing_section_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, None)
        _ = graph.post(_SECTION_ROUTE).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ItemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _create(client, section=_SECTION_URI)

    async def test_a_404_on_the_section_read_is_a_not_found_and_nothing_is_posted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_SECTION_AUDIENCE_ROUTE).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ItemNotFound", "message": "not found"}}
            )
        )
        create = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))

        with pytest.raises(GraphNotFound):
            _ = await _create(client, section=_SECTION_URI)

        assert create.call_count == 0

    async def test_a_404_on_the_notebook_read_is_a_not_found_and_nothing_is_posted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = graph.get(_NOTEBOOK_ROUTE).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ItemNotFound", "message": "not found"}}
            )
        )
        create = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))

        with pytest.raises(GraphNotFound):
            _ = await _create(client, section=_SECTION_URI)

        assert create.call_count == 0

    async def test_the_call_example_reaches_graph_and_the_notebooks_read_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", creator.GRAPH_CALL_EXAMPLE)
        refused = graph.get(_NOTEBOOKS_ROUTE).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )
        create = graph.post(_DEFAULT_ROUTE).mock(return_value=httpx.Response(201))

        with pytest.raises(GraphForbidden):
            _ = await _create(client, title=example["title"], body_html=example["body_html"])

        assert refused.call_count == 1
        assert create.call_count == 0

    def test_the_not_found_advice_points_back_to_onenote_list_notebooks(self) -> None:
        assert "onenote_list_notebooks" in creator.GRAPH_NOT_FOUND


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_create(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("Notes.Create",)

    def test_the_call_example_is_arguments_the_tool_accepts(self) -> None:
        assert set(creator.GRAPH_CALL_EXAMPLE) <= {"title", "body_html", "section"}
        assert "title" in creator.GRAPH_CALL_EXAMPLE
        assert "body_html" in creator.GRAPH_CALL_EXAMPLE

    async def test_it_announces_itself_as_a_write_that_destroys_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_it_takes_four_arguments_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"title", "body_html", "section", "section_name"}
        assert cast("list[str]", parameters["required"]) == ["title", "body_html"]

    async def test_the_description_says_it_writes_now_and_cannot_attach(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "right now" in description
        assert "no way to attach a file or an image" in description
        assert "onenote_append_to_page" in description
        assert "onenote_list_pages" in description

    async def test_the_description_says_when_it_asks_and_when_it_does_not(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "shared with other people or belongs to somebody else" in description
        assert "written without a question" in description

    async def test_the_description_covers_section_name(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "section_name" in description
        assert "creating a new section there under that name" in description
        assert "?" in description and "~" in description

    async def test_no_argument_offers_an_attachment(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if "attach" in name.casefold()]
        assert not [name for name in properties if "image" in name.casefold()]
        assert not [name for name in properties if "file" in name.casefold()]


class TestThePersonBetweenTheRequestAndThePage:
    async def test_the_users_own_unshared_notebook_asks_nobody_and_writes_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _own_unshared_section(graph)
        route = _creates(graph, _SECTION_ROUTE, _page_payload())
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            asked.append(question)
            assert about
            return None

        _ = await _create(client, section=_SECTION_URI, confirm=counting)

        assert asked == [], "the person was interrupted for a page nobody else can see"
        assert route.call_count == 1
        calls = _calls(graph)
        assert calls[0].request.method == "GET"
        assert calls[-1].request.method == "POST"

    async def test_a_shared_notebook_is_asked_about_and_a_refusal_writes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=True, user_role="Owner")
        route = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))

        with pytest.raises(ToolError, match="No page was created"):
            _ = await create_page(
                client,
                title=_TITLE,
                body_html=_BODY_HTML,
                section=_SECTION_URI,
                confirm=_refuses,
            )

        assert route.call_count == 0, "a declined create still reached the notebook"

    async def test_a_contributor_role_on_an_unshared_notebook_is_still_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=False, user_role="Contributor")
        _ = _creates(graph, _SECTION_ROUTE, _page_payload())
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, section=_SECTION_URI, confirm=counting)

        assert len(asked) == 1

    async def test_a_notebook_with_no_sharing_fields_at_all_is_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=None, user_role=None)
        _ = _creates(graph, _SECTION_ROUTE, _page_payload())
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, section=_SECTION_URI, confirm=counting)

        assert len(asked) == 1

    async def test_a_default_route_with_an_empty_notebooks_collection_asks_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _no_default_notebook(graph)
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, confirm=counting)

        assert asked == [], "nothing exists yet, so nobody else could be reached"
        assert route.call_count == 1

    async def test_a_default_route_with_a_shared_default_notebook_is_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_default_notebooks(graph, _notebook_payload(is_shared=True, user_role="Owner"))
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload())
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, confirm=counting)

        assert len(asked) == 1

    async def test_a_section_whose_read_names_no_parent_notebook_is_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, None)
        _ = _creates(graph, _SECTION_ROUTE, _page_payload())
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, section=_SECTION_URI, confirm=counting)

        assert len(asked) == 1

    async def test_a_client_that_cannot_ask_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=True, user_role="Owner")
        route = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))
        confirm = a_person_agrees(_context(RuntimeError("elicitation not supported")))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await create_page(
                client, title=_TITLE, body_html=_BODY_HTML, section=_SECTION_URI, confirm=confirm
            )

        assert route.call_count == 0

    async def test_the_question_names_the_title_the_notebook_the_reason_and_the_opening(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=True, user_role="Owner")
        _ = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201, json=_page_payload()))
        asked: list[str] = []
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            asked.append(question)
            bound.append(about)
            return None

        _ = await _create(
            client,
            section=_SECTION_URI,
            title="Q4 planning",
            body_html="<p>Ship the plan by Friday.</p>",
            confirm=capturing,
        )

        assert len(asked) == 1
        question = asked[0]
        assert "Q4 planning" in question
        assert _NOTEBOOK_NAME in question
        assert "which is shared with other people" in question
        assert "Ship the plan by Friday." in question
        assert bound[0]

    async def test_a_notebook_graph_named_nothing_falls_back_to_an_unnamed_notebook(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, name=None, is_shared=True, user_role="Owner")
        _ = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201, json=_page_payload()))
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, section=_SECTION_URI, confirm=capturing)

        assert "an unnamed notebook" in asked[0]

    async def test_a_not_owner_role_names_the_role_in_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=False, user_role="Contributor")
        _ = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201, json=_page_payload()))
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, section=_SECTION_URI, confirm=capturing)

        assert "belongs to somebody else (you are Contributor)" in asked[0]

    async def test_a_notebook_with_neither_field_reported_says_sharing_was_not_reported(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=None, user_role=None)
        _ = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201, json=_page_payload()))
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _create(client, section=_SECTION_URI, confirm=capturing)

        assert "whose sharing Microsoft did not report" in asked[0]

    async def test_two_identical_calls_compose_the_same_about_and_a_changed_body_a_different_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=True, user_role="Owner")
        _ = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201, json=_page_payload()))
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _create(client, section=_SECTION_URI, body_html="<p>one</p>", confirm=capturing)
        _ = await _create(client, section=_SECTION_URI, body_html="<p>one</p>", confirm=capturing)
        _ = await _create(client, section=_SECTION_URI, body_html="<p>two</p>", confirm=capturing)

        assert bound[0] == bound[1]
        assert bound[0] != bound[2]

    async def test_about_matches_write_state_for_create_and_the_section_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=True, user_role="Owner")
        _ = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201, json=_page_payload()))
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _create(client, section=_SECTION_URI, confirm=capturing)

        assert bound[0] == write_state_for("create", _SECTION_ID, _TITLE, _BODY_HTML)


def _context(answer: object) -> Context:
    class _Client:
        request_context: object = None

        async def elicit(self, message: str, response_type: object = None) -> object:
            assert message
            assert response_type is not None, "the caller must say what it expects back"
            if isinstance(answer, Exception):
                raise answer
            return answer

    return cast("Context", cast("object", _Client()))


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


def _modern_context(
    *, answers: Mapping[str, InputResponse] | None = None, state: str | None = None
) -> Context:
    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, InputResponse] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            raise AssertionError(
                f"a connection with no back-channel was asked {message!r} over it, "
                + f"expecting {response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


async def _round(
    client: GraphServiceClient,
    *,
    confirm: Confirm,
    section: str | None = _SECTION_URI,
    answer_pending: bool = False,
) -> CreatedPage | InputRequiredResult:
    return await create_page(
        client,
        title=_TITLE,
        body_html=_BODY_HTML,
        section=section,
        confirm=confirm,
        answer_pending=answer_pending,
    )


def _the_question(answer: CreatedPage | InputRequiredResult) -> tuple[str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams), "the question is not one a client can fill"
    assert params.message, "the person is asked nothing at all"
    schema = cast("Mapping[str, object]", params.requested_schema)
    properties = cast("Mapping[str, object]", schema["properties"])
    value = cast("Mapping[str, object]", properties["value"])
    choices = cast("list[str]", value["enum"])
    assert len(choices) == 2, f"a confirmation offers two answers, this one offered {choices}"
    assert answer.request_state is not None, "the answer was bound to nothing"
    return key, answer.request_state, choices[0]


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=True, user_role="Owner")
        create = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))

        answer = await _round(client, confirm=a_person_agrees(_modern_context()))

        _key, _state, _agree = _the_question(answer)
        assert read.call_count == 1
        assert create.call_count == 0, "an unanswered question created the page anyway"

    async def test_the_second_round_creates_the_page_under_the_id_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=True, user_role="Owner")
        create = graph.post(_SECTION_ROUTE).mock(
            return_value=httpx.Response(201, json=_page_payload())
        )
        key, state, agree = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )
        assert state == write_state_for("create", _SECTION_ID, _TITLE, _BODY_HTML)

        answer = await _round(
            client,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agree})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, CreatedPage)
        assert create.call_count == 1, "the confirmed create did not happen exactly once"

    async def test_a_second_round_the_person_declined_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=True, user_role="Owner")
        create = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))
        key, state, _agree = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="did not agree") as raised:
            _ = await _round(
                client,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
            )

        assert str(raised.value).startswith("No page was created.")
        assert create.call_count == 0

    async def test_an_answer_bound_to_another_request_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        _ = _reads_notebook(graph, is_shared=True, user_role="Owner")
        create = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))
        key, _state, agree = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _round(
                client,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": agree})},
                        state="synthetic-other-state",
                    )
                ),
            )

        assert create.call_count == 0

    async def test_a_pending_decline_is_honored_even_when_the_fresh_read_says_private(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        notebook_route = graph.get(_NOTEBOOK_ROUTE).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        create = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))
        key, state, _agree = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="did not agree") as raised:
            _ = await _round(
                client,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
                answer_pending=True,
            )

        assert str(raised.value).startswith("No page was created.")
        assert create.call_count == 0
        assert notebook_route.call_count == 2

    async def test_a_pending_accept_still_creates_when_the_fresh_read_says_private(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        notebook_route = graph.get(_NOTEBOOK_ROUTE).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        create = graph.post(_SECTION_ROUTE).mock(
            return_value=httpx.Response(201, json=_page_payload())
        )
        key, state, agree = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        answer = await _round(
            client,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agree})},
                    state=state,
                )
            ),
            answer_pending=True,
        )

        assert isinstance(answer, CreatedPage)
        assert create.call_count == 1
        assert notebook_route.call_count == 2


class TestHowRegisterWiresThePendingAnswer:
    async def test_register_consults_a_pending_answer_the_fresh_read_alone_would_skip(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_section_parent(graph, _NOTEBOOK_ID)
        notebook_route = graph.get(_NOTEBOOK_ROUTE).mock(
            side_effect=[
                httpx.Response(200, json=_notebook_payload(is_shared=True, user_role="Owner")),
                httpx.Response(200, json=_notebook_payload(is_shared=False, user_role="Owner")),
            ]
        )
        create = graph.post(_SECTION_ROUTE).mock(return_value=httpx.Response(201))
        mcp: FastMCP = FastMCP(name="wiring-under-test")
        creator.register(mcp, transport)
        tool = await mcp.get_tool(creator.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"
        assert isinstance(tool, FunctionTool)

        first = cast(
            "CreatedPage | InputRequiredResult",
            await tool.fn(
                title=_TITLE,
                body_html=_BODY_HTML,
                section=_SECTION_URI,
                ctx=_modern_context(),
                client=client,
            ),
        )
        key, state, _agree = _the_question(first)

        with pytest.raises(ToolError, match="did not agree"):
            _ = cast(
                "CreatedPage | InputRequiredResult",
                await tool.fn(
                    title=_TITLE,
                    body_html=_BODY_HTML,
                    section=_SECTION_URI,
                    ctx=_modern_context(answers={key: ElicitResult(action="decline")}, state=state),
                    client=client,
                ),
            )

        assert create.call_count == 0
        assert notebook_route.call_count == 2
