import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import OnenotePageHandle, OnenoteSectionHandle
from office_365_mcp.shared.notes import PageSummary
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import onenote_append_to_page as appender

_PAGE_ID = "1-SYNTHETICPAGE00000000000000000000!0-ABCDEF"

_PAGE_URI = OnenotePageHandle(_PAGE_ID).uri

_BODY_HTML = "<p>Synthetic addition.</p>"

_PATCH_PATH = f"/me/onenote/pages/{_PAGE_ID}/onenotePatchContent"

_GET_PATH = f"/me/onenote/pages/{_PAGE_ID}"


def _page_payload(
    *,
    page_id: str | None = _PAGE_ID,
    title: str | None = "Meeting notes",
    created: str | None = "2026-01-01T00:00:00Z",
    last_modified: str | None = "2026-01-05T12:30:00Z",
    web_url: str | None = "https://onenote.example.invalid/web",
    client_url: str | None = "https://onenote.example.invalid/client",
    section: Mapping[str, object] | None = None,
    notebook: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": page_id,
        "title": title,
        "createdDateTime": created,
        "lastModifiedDateTime": last_modified,
        "links": {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        },
        "parentSection": dict(section) if section is not None else None,
        "parentNotebook": dict(notebook) if notebook is not None else None,
    }


_SECTION = {"id": "SECTION1", "displayName": "General"}
_NOTEBOOK = {"id": "NOTEBOOK1", "displayName": "Work"}


def _patches(graph: respx.MockRouter, *, status: int = 204) -> respx.Route:
    return graph.post(_PATCH_PATH).mock(return_value=httpx.Response(status))


def _rereads(graph: respx.MockRouter, payload: Mapping[str, object]) -> respx.Route:
    return graph.get(_GET_PATH).mock(return_value=httpx.Response(200, json=dict(payload)))


async def _append(
    client: GraphServiceClient, *, page: str = _PAGE_URI, body_html: str = _BODY_HTML
) -> PageSummary:
    return await appender.append_to_page(client, page=page, body_html=body_html)


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    appender.register(mcp, transport)
    tool = await mcp.get_tool(appender.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_patches_the_content_then_rereads_the_page_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph)
        reread = _rereads(graph, _page_payload())

        _ = await _append(client)

        assert patch.call_count == 1
        assert reread.call_count == 1
        assert len(graph.calls) == 2, "an append costs the patch and the re-read, nothing else"

    async def test_the_patch_happens_before_the_reread(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(graph, _page_payload())

        _ = await _append(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [call.request.method for call in made] == ["POST", "GET"]
        assert made[0].request.url.path.endswith(_PATCH_PATH)
        assert made[1].request.url.path.endswith(_GET_PATH)

    async def test_the_patch_is_sent_as_one_append_command_with_the_body_verbatim(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph)
        _ = _rereads(graph, _page_payload())

        _ = await _append(client, body_html="<p>one</p><p>two</p>")

        assert _sent(patch) == {
            "commands": [
                {
                    "action": "Append",
                    "content": "<p>one</p><p>two</p>",
                    "position": "After",
                    "target": "body",
                }
            ]
        }

    async def test_the_patch_content_type_is_json(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph)
        _ = _rereads(graph, _page_payload())

        _ = await _append(client)

        assert patch.calls.last.request.headers["content-type"] == "application/json"

    async def test_the_reread_asks_for_the_same_fields_a_page_listing_would(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        reread = _rereads(graph, _page_payload())

        _ = await _append(client)

        query = reread.calls.last.request.url.params
        assert query["$select"] == "id,title,createdDateTime,lastModifiedDateTime,links"
        assert query["$expand"] == "parentSection,parentNotebook"

    async def test_the_body_html_reaches_graph_byte_for_byte(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph)
        _ = _rereads(graph, _page_payload())
        written = "<ul><li>a &amp; b</li></ul><table><tr><td>x</td></tr></table>"

        _ = await _append(client, body_html=written)

        commands = cast("list[dict[str, object]]", _sent(patch)["commands"])
        assert commands[0]["content"] == written

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_patch_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = graph.post(_PATCH_PATH).mock(return_value=httpx.Response(503))
        reread = graph.get(_GET_PATH).mock(return_value=httpx.Response(200, json=_page_payload()))

        with pytest.raises(GraphUnavailable):
            _ = await _append(client)

        assert patch.call_count == 1, "no_retry means one attempt, however Graph answers"
        assert reread.call_count == 0, "a failed write is never followed by the re-read"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            OnenoteSectionHandle("SECTION1").uri,
            "1-SYNTHETICPAGE00000000000000000000!0-ABCDEF",
            "https://onenote.example.invalid/page/1-SYNTHETICPAGE",
            "Meeting notes",
            "",
            "   ",
            "onenote:///pages/",
            "onenote:///pages/%20",
        ],
    )
    async def test_a_value_that_is_not_a_page_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _append(client, page=value)

        assert len(graph.calls) == 0, "a refused handle writes nothing"

    async def test_the_refusal_names_the_tool_that_mints_a_page_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_pages"):
            _ = await _append(client, page="Meeting notes")

    async def test_a_section_handle_is_refused_by_name(self, client: GraphServiceClient) -> None:
        with pytest.raises(ToolError, match="section handle"):
            _ = await _append(client, page=OnenoteSectionHandle("SECTION1").uri)


class TestWhatItAnswers:
    async def test_the_answer_is_the_page_as_graph_holds_it_after_the_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(
            graph,
            _page_payload(
                title="Updated title",
                last_modified="2026-01-09T08:00:00Z",
                section=_SECTION,
                notebook=_NOTEBOOK,
            ),
        )

        answer = await _append(client)

        assert answer.uri == _PAGE_URI
        assert answer.title == "Updated title"
        assert answer.last_modified_at is not None
        assert answer.last_modified_at.isoformat() == "2026-01-09T08:00:00+00:00"
        assert answer.section_name == "General"
        assert answer.notebook_name == "Work"
        assert answer.section_uri == OnenoteSectionHandle("SECTION1").uri

    async def test_the_answer_is_read_off_graph_and_never_echoes_the_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(graph, _page_payload(title="Untouched by the argument"))

        answer = await _append(client, body_html="<p>ignored for the assertion</p>")

        assert "ignored for the assertion" not in answer.model_dump_json()
        assert answer.title == "Untouched by the argument"

    async def test_nulls_when_graph_names_no_parent_section_or_notebook(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(graph, _page_payload(section=None, notebook=None))

        answer = await _append(client)

        assert answer.section_uri is None
        assert answer.section_name is None
        assert answer.notebook_name is None

    async def test_nulls_when_graph_names_no_web_or_client_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(graph, _page_payload(web_url=None, client_url=None))

        answer = await _append(client)

        assert answer.web_url is None
        assert answer.client_url is None

    async def test_a_reread_that_names_no_id_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        _ = _rereads(graph, _page_payload(page_id=None))

        with pytest.raises(AssertionError):
            _ = await _append(client)


class TestGraphFailures:
    async def test_a_404_on_the_patch_is_a_not_found_and_the_page_is_never_reread(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = graph.post(_PATCH_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )
        reread = graph.get(_GET_PATH).mock(return_value=httpx.Response(200, json=_page_payload()))

        with pytest.raises(GraphNotFound):
            _ = await _append(client)

        assert patch.call_count == 1
        assert reread.call_count == 0

    async def test_a_403_on_the_patch_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATCH_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _append(client)

    async def test_a_404_on_the_reread_is_a_not_found_and_the_patch_was_sent_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _patches(graph, status=204)
        reread = graph.get(_GET_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _append(client)

        assert patch.call_count == 1
        assert reread.call_count == 1


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_readwrite(self) -> None:
        assert appender.GRAPH_PERMISSIONS == ("Notes.ReadWrite",)

    def test_the_call_example_is_a_page_handle_and_body(self) -> None:
        assert set(appender.GRAPH_CALL_EXAMPLE) == {"page", "body_html"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(appender.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_two_arguments_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"page", "body_html"}

    async def test_it_announces_itself_as_an_additive_write(
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

    async def test_the_description_says_what_it_cannot_do(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "end" in description
        assert "cannot" in description
        assert "onenote_read_page" in description
        assert "nobody is notified" in description

    def test_not_found_advice_points_at_the_lister(self) -> None:
        assert "onenote_list_pages" in appender.GRAPH_NOT_FOUND
