from collections.abc import AsyncIterator, Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import (
    OnenotePageHandle,
    OnenoteSectionHandle,
    onenote_page_handle,
)
from office_365_mcp.tools import onenote_read_page as reader

from .conftest import GRAPH_V1

PAGE_ID = "0-SYNTHETICPAGE0000!0001"
SECTION_ID = "0-SYNTHETICSECTION00!0001"

_PAGE_PATH = "/me/onenote/pages/0-SYNTHETICPAGE0000%210001"
_CONTENT_PATH = f"{_PAGE_PATH}/content"

_PAGE = OnenotePageHandle(PAGE_ID).uri
_SECTION = OnenoteSectionHandle(SECTION_ID).uri

_WEB_URL = "https://onenote.example.invalid/pages/sprint-notes"
_CLIENT_URL = "onenote:https://onenote.example.invalid/pages/sprint-notes"

_HTML = b"<html><head><title>Sprint notes</title></head><body><div>hi</div></body></html>"


def _page_payload(
    *,
    page_id: str = PAGE_ID,
    title: str | None = "Sprint notes",
    created: str | None = "2026-03-01T09:00:00Z",
    modified: str | None = "2026-03-04T10:30:00Z",
    web_url: str | None = _WEB_URL,
    client_url: str | None = _CLIENT_URL,
    section_id: str | None = SECTION_ID,
    section_name: str | None = "Engineering",
    notebook_name: str | None = "Team Notebook",
    links: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": page_id,
        "title": title,
        "createdDateTime": created,
        "lastModifiedDateTime": modified,
    }
    if links:
        payload["links"] = {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        }
    else:
        payload["links"] = None
    if section_id is not None:
        payload["parentSection"] = {"id": section_id, "displayName": section_name}
    else:
        payload["parentSection"] = None
    payload["parentNotebook"] = (
        {"displayName": notebook_name} if notebook_name is not None else None
    )
    return payload


@pytest.fixture
def page(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_PAGE_PATH).mock(return_value=httpx.Response(200, json=_page_payload()))


@pytest.fixture
def content(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_CONTENT_PATH).mock(
        return_value=httpx.Response(200, content=_HTML, headers={"content-type": "text/html"})
    )


async def _read(
    client: GraphServiceClient,
    transport: httpx.AsyncClient,
    *,
    page: str = _PAGE,
    include_ids: bool = False,
) -> reader.PageContent:
    return await reader.onenote_read_page(client, transport, page=page, include_ids=include_ids)


class TestWhatItAsks:
    @pytest.mark.usefixtures("content")
    async def test_it_selects_and_expands_the_fields_every_page_tool_agrees_on(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, page: respx.Route
    ) -> None:
        _ = await _read(client, transport)

        params = page.calls.last.request.url.params
        assert params["$select"].split(",") == [
            "id",
            "title",
            "createdDateTime",
            "lastModifiedDateTime",
            "links",
        ]
        assert params["$expand"].split(",") == ["parentSection", "parentNotebook"]

    @pytest.mark.usefixtures("page")
    async def test_the_content_request_carries_no_query_parameters_at_all(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, content: respx.Route
    ) -> None:
        _ = await _read(client, transport)

        assert content.calls.last.request.url.params == httpx.QueryParams()

    async def test_both_requests_are_addressed_by_the_same_percent_encoded_id(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        page: respx.Route,
        content: respx.Route,
    ) -> None:
        _ = await _read(client, transport)

        assert page.call_count == 1
        assert content.call_count == 1
        page_raw_path = page.calls.last.request.url.raw_path.split(b"?")[0]
        assert page_raw_path == httpx.URL(f"{GRAPH_V1}{_PAGE_PATH}").raw_path
        assert (
            content.calls.last.request.url.raw_path
            == httpx.URL(f"{GRAPH_V1}{_CONTENT_PATH}").raw_path
        )
        assert b"%21" in page_raw_path


class TestWhatItAnswers:
    async def test_the_page_summary_is_mapped_from_graph(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        page: respx.Route,
        content: respx.Route,
    ) -> None:
        answer = await _read(client, transport)

        summary = answer.page
        assert summary.uri == OnenotePageHandle(PAGE_ID).uri
        assert summary.title == "Sprint notes"
        assert summary.web_url == _WEB_URL
        assert summary.client_url == _CLIENT_URL
        assert summary.section_uri == OnenoteSectionHandle(SECTION_ID).uri
        assert summary.section_name == "Engineering"
        assert summary.notebook_name == "Team Notebook"
        assert (page.call_count, content.call_count) == (1, 1)

    async def test_the_html_comes_back_decoded_exactly_as_graph_sent_it(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        page: respx.Route,
        content: respx.Route,
    ) -> None:
        answer = await _read(client, transport)

        assert answer.html == _HTML.decode("utf-8")
        assert (page.call_count, content.call_count) == (1, 1)

    async def test_a_page_graph_named_no_parent_for_answers_null_handles(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        content: respx.Route,
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(
            return_value=httpx.Response(
                200,
                json=_page_payload(section_id=None, notebook_name=None, links=False),
            )
        )

        answer = await _read(client, transport)

        assert answer.page.section_uri is None
        assert answer.page.section_name is None
        assert answer.page.notebook_name is None
        assert answer.page.web_url is None
        assert answer.page.client_url is None
        assert content.call_count == 1


class TestTheSizeCap:
    async def test_content_exactly_at_the_cap_is_returned(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        page: respx.Route,
        graph: respx.MockRouter,
    ) -> None:
        body = b"<html>" + b"a" * (reader.MAX_CONTENT_BYTES - len(b"<html></html>")) + b"</html>"
        assert len(body) == reader.MAX_CONTENT_BYTES
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=body))

        answer = await _read(client, transport)

        assert answer.html == body.decode("utf-8")
        assert page.call_count == 1

    async def test_content_over_the_cap_is_refused_and_names_the_web_url(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        page: respx.Route,
        graph: respx.MockRouter,
    ) -> None:
        body = b"x" * (reader.MAX_CONTENT_BYTES + 1)
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=body))

        with pytest.raises(ToolError) as refused:
            _ = await _read(client, transport)

        refusal = str(refused.value)
        assert f"{len(body):,} bytes" in refusal
        assert "1,048,577 bytes" in refusal
        assert "1,048,576 bytes" in refusal
        assert _WEB_URL in refusal
        assert "arrive in one message" in refusal
        assert page.call_count == 1

    async def test_a_declared_length_over_the_cap_is_refused_before_a_second_request(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        page: respx.Route,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Graph declares the length, so this is refused before a byte of it is read."""
        monkeypatch.setattr(reader, "MAX_CONTENT_BYTES", 64)
        body = b"x" * 100
        route = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=body))

        with pytest.raises(ToolError) as refused:
            _ = await _read(client, transport)

        assert f"{len(body):,} bytes" in str(refused.value)
        assert _WEB_URL in str(refused.value)
        assert route.call_count == 1, "the declared length refused this before a retry"
        assert page.call_count == 1

    async def test_an_undeclared_length_over_the_cap_is_refused_on_the_bytes_counted(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        page: respx.Route,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Chunked with no Content-Length, so the streamed-bytes guard fires instead."""
        monkeypatch.setattr(reader, "MAX_CONTENT_BYTES", 64)

        async def chunks() -> AsyncIterator[bytes]:
            for _ in range(4):
                yield b"x" * 40

        graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=chunks()))

        with pytest.raises(ToolError) as refused:
            _ = await _read(client, transport)

        assert "content-length" not in str(refused.value).casefold(), "nothing was declared"
        assert "160 bytes" in str(refused.value), "what it had counted when it stopped"
        assert _WEB_URL in str(refused.value)
        assert page.call_count == 1

    async def test_a_size_refusal_without_a_web_url_still_advises_something(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(
            return_value=httpx.Response(200, json=_page_payload(web_url=None))
        )
        body = b"x" * (reader.MAX_CONTENT_BYTES + 1)
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=body))

        with pytest.raises(ToolError, match="Microsoft gave no web address"):
            _ = await _read(client, transport)


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            _SECTION,
            PAGE_ID,
            "https://onenote.example.invalid/pages/sprint-notes",
            "Sprint notes",
            "onenote:///pages/",
        ],
    )
    async def test_a_value_that_is_not_a_page_handle_never_reaches_graph(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        value: str,
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_pages"):
            _ = await _read(client, transport, page=value)

        assert graph.calls.call_count == 0

    async def test_the_refusal_names_the_page_handle_shape(
        self, client: GraphServiceClient, transport: httpx.AsyncClient
    ) -> None:
        with pytest.raises(ToolError, match=r"onenote:///pages/\{id\}") as refused:
            _ = await _read(client, transport, page=_SECTION)

        assert "onenote:///sections/{id}" in str(refused.value)


class TestGraphFailures:
    async def test_a_404_on_the_page_is_a_graph_not_found(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _read(client, transport)

    async def test_a_403_on_the_page_is_a_graph_forbidden(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PAGE_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _read(client, transport)

    @pytest.mark.usefixtures("page")
    async def test_a_404_on_the_content_is_a_graph_not_found(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CONTENT_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _read(client, transport)

    @pytest.mark.usefixtures("page")
    async def test_no_content_at_all_is_refused_rather_than_answered_empty(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=b""))

        with pytest.raises(ToolError, match="sent no content"):
            _ = await _read(client, transport)

    @pytest.mark.usefixtures("page")
    async def test_content_that_is_not_valid_utf8_is_refused_and_names_the_web_url(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        not_utf8 = "<html>café</html>".encode("utf-16")
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=not_utf8))

        with pytest.raises(ToolError, match="cannot decode") as refused:
            _ = await _read(client, transport)

        assert "not valid UTF-8" in str(refused.value)
        assert _WEB_URL in str(refused.value)


class TestHowItDeclaresItself:
    def test_the_permission_is_the_read_one_microsoft_documents(self) -> None:
        assert reader.GRAPH_PERMISSIONS == ("Notes.Read",)

    def test_each_graph_call_has_a_step_of_its_own(self) -> None:
        assert (reader.STEP_PAGE, reader.STEP_PAGE_CONTENT) == ("page", "page_content")

    def test_the_refusable_call_is_a_handle_this_tool_accepts(self) -> None:
        assert set(reader.GRAPH_CALL_EXAMPLE) == {"page"}
        example = cast("str", reader.GRAPH_CALL_EXAMPLE["page"])
        assert onenote_page_handle(example) is not None

    def test_a_stale_handle_is_answered_with_the_recovery_that_works(self) -> None:
        assert "onenote_list_pages" in reader.GRAPH_NOT_FOUND
        assert "do not retry" in reader.GRAPH_NOT_FOUND

    async def test_it_announces_itself_as_reading_and_changing_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        reader.register(mcp, transport)

        tool = await mcp.get_tool(reader.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.title == "Read Page"

    async def test_the_description_names_the_cap_and_the_append_tool(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        reader.register(mcp, transport)
        tool = await mcp.get_tool(reader.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"

        described = tool.description or ""
        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        page_property = cast("Mapping[str, object]", properties["page"])
        page_described = cast("str", page_property["description"])

        assert "onenote_list_pages" in page_described
        assert "onenote_create_page" in page_described
        assert "onenote_append_to_page" in described
        assert "1 MB" in described
        assert "opens only with this connector's own sign-in token" in described
        assert "This tool converts nothing" in described
        assert "onenote_edit_page" in described
        assert "include_ids" in described

    async def test_it_takes_the_page_handle_and_include_ids(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        reader.register(mcp, transport)
        tool = await mcp.get_tool(reader.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"

        parameters = tool.parameters
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"page", "include_ids"}
        assert parameters["required"] == ["page"]


class TestIncludeIds:
    @pytest.mark.usefixtures("page")
    async def test_by_default_no_query_parameter_is_sent(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, content: respx.Route
    ) -> None:
        _ = await _read(client, transport)

        assert content.calls.last.request.url.params == httpx.QueryParams()

    @pytest.mark.usefixtures("page")
    async def test_include_ids_true_sends_the_raw_query_parameter(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, content: respx.Route
    ) -> None:
        _ = await _read(client, transport, include_ids=True)

        assert content.calls.last.request.url.params["includeIDs"] == "true"

    @pytest.mark.usefixtures("content")
    async def test_include_ids_does_not_reach_the_page_metadata_call(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, page: respx.Route
    ) -> None:
        _ = await _read(client, transport, include_ids=True)

        assert "includeIDs" not in page.calls.last.request.url.params
