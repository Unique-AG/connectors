from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import (
    OnenotePageHandle,
    OnenoteSectionHandle,
    onenote_page_handle,
)
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import onenote_create_page as creator
from office_365_mcp.tools.onenote_create_page import CreatedPage

_DEFAULT_ROUTE = "/me/onenote/pages"

_SECTION_ID = "0-EB2FEEF7DCFC3C6B!12345"
_SECTION_URI = OnenoteSectionHandle(_SECTION_ID).uri
_SECTION_ROUTE = "/me/onenote/sections/0-EB2FEEF7DCFC3C6B%2112345/pages"

_PAGE_ID = "0-EB2FEEF7DCFC3C6B!1-0"

_OTHER_SECTION_ID = "0-AAAAAAAAAAAAAAAA!99999"

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


async def _create(client: GraphServiceClient, **overrides: object) -> CreatedPage:
    arguments: dict[str, object] = {"title": _TITLE, "body_html": _BODY_HTML}
    arguments.update(overrides)
    now = cast("Callable[[], datetime]", arguments.pop("now", lambda: _NOW))
    return await creator.create_page(
        client,
        title=cast("str", arguments["title"]),
        body_html=cast("str", arguments["body_html"]),
        section=cast("str | None", arguments.get("section")),
        now=now,
    )


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
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client)

        assert route.call_count == 1
        assert route.calls.last.request.method == "POST"

    async def test_it_posts_to_the_section_route_when_a_section_handle_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        default_route = graph.post(_DEFAULT_ROUTE).mock(return_value=httpx.Response(201))
        route = _creates(graph, _SECTION_ROUTE, _page_payload())

        _ = await _create(client, section=_SECTION_URI)

        assert route.call_count == 1
        assert default_route.call_count == 0

    async def test_the_content_type_is_exactly_text_html(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client)

        assert route.calls.last.request.headers["Content-Type"] == "text/html"

    async def test_it_asks_for_json_back(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client)

        assert route.calls.last.request.headers["Accept"] == "application/json"

    async def test_the_body_bytes_are_exactly_the_envelope_with_an_escaped_title(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())
        written = '<p>Q1 &amp; Q2 &mdash; 100% done. "quoted" <b>bold</b></p>'

        _ = await _create(client, body_html=written)

        sent = route.calls.last.request.content.decode("utf-8")
        assert f"<body>{written}</body>" in sent

    async def test_it_creates_exactly_one_page_per_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        _ = await _create(client)

        assert len(graph.calls) == 1
        assert route.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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


class TestWhatItAnswers:
    async def test_the_handle_is_minted_from_the_id_graph_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(page_id=_PAGE_ID))

        answer = await _create(client)

        assert answer.uri == OnenotePageHandle(_PAGE_ID).uri
        handle = onenote_page_handle(answer.uri)
        assert handle is not None
        assert handle.page_id == _PAGE_ID

    async def test_the_title_is_read_off_graph_and_not_echoed_from_the_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(title="Q4 planning (renamed)"))

        answer = await _create(client, title=_TITLE)

        assert answer.title == "Q4 planning (renamed)"

    async def test_the_links_are_read_off_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        answer = await _create(client)

        assert answer.web_url == _WEB_URL
        assert answer.client_url == _CLIENT_URL

    async def test_missing_links_answer_null_rather_than_a_built_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(web_url=None, client_url=None))

        answer = await _create(client)

        assert answer.web_url is None
        assert answer.client_url is None

    async def test_created_at_is_read_off_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(created_at=_CREATED_AT))

        answer = await _create(client)

        assert answer.created_at == datetime.fromisoformat(_CREATED_AT.replace("Z", "+00:00"))

    async def test_section_uri_is_the_handle_this_call_wrote_into(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _SECTION_ROUTE, _page_payload())

        answer = await _create(client, section=_SECTION_URI)

        assert answer.section_uri == _SECTION_URI

    async def test_section_uri_is_none_when_the_default_section_was_used_and_graph_named_none(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload())

        answer = await _create(client)

        assert answer.section_uri is None

    async def test_section_uri_prefers_graphs_own_parent_section_over_the_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _SECTION_ROUTE, _page_payload(parent_section_id=_OTHER_SECTION_ID))

        answer = await _create(client, section=_SECTION_URI)

        assert answer.section_uri == OnenoteSectionHandle(_OTHER_SECTION_ID).uri

    async def test_section_uri_is_read_off_graph_even_for_the_default_section(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(parent_section_id=_OTHER_SECTION_ID))

        answer = await _create(client)

        assert answer.section_uri == OnenoteSectionHandle(_OTHER_SECTION_ID).uri

    async def test_a_201_with_no_id_is_an_invariant_violation(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _DEFAULT_ROUTE, _page_payload(page_id=None))

        with pytest.raises(AssertionError):
            _ = await _create(client)


class TestTheFailuresItPassesOn:
    async def test_a_refused_create_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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
        _ = graph.post(_SECTION_ROUTE).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ItemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _create(client, section=_SECTION_URI)

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

    async def test_it_takes_three_arguments_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"title", "body_html", "section"}
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

    async def test_no_argument_offers_an_attachment(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if "attach" in name.casefold()]
        assert not [name for name in properties if "image" in name.casefold()]
        assert not [name for name in properties if "file" in name.casefold()]
