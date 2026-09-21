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
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import onenote_find_notebook_from_url as finder

NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK0000!0001"

_WEB_URL = "https://onenote.example.invalid/notebooks/team-notebook"
_CLIENT_URL = "onenote:https://onenote.example.invalid/notebooks/team-notebook"

_PATH = "/me/onenote/notebooks/getNotebookFromWebUrl"


def _notebook_payload(
    *,
    notebook_id: str | None = NOTEBOOK_ID,
    name: str | None = "Team Notebook",
    is_default: bool | None = True,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
    web_url: str | None = _WEB_URL,
    client_url: str | None = _CLIENT_URL,
    created: str | None = "2026-01-05T09:30:00Z",
    modified: str | None = "2026-03-12T14:45:00Z",
    links: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": notebook_id,
        "name": name,
        "isDefault": is_default,
        "isShared": is_shared,
        "userRole": user_role,
        "createdTime": created,
        "lastModifiedTime": modified,
    }
    if links:
        payload["links"] = {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        }
    else:
        payload["links"] = None
    return payload


@pytest.fixture
def found(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_PATH).mock(return_value=httpx.Response(200, json=_notebook_payload()))


async def _find(client: GraphServiceClient, *, web_url: str = _WEB_URL) -> finder.FoundNotebook:
    return await finder.find_notebook_from_url(client, web_url=web_url)


class TestWhatItAsks:
    async def test_it_sends_the_web_url_verbatim_in_the_body(
        self, client: GraphServiceClient, found: respx.Route
    ) -> None:
        _ = await _find(client)

        sent = cast("dict[str, object]", json.loads(found.calls.last.request.content))
        assert sent == {"webUrl": _WEB_URL}

    async def test_the_request_carries_no_query_parameters(
        self, client: GraphServiceClient, found: respx.Route
    ) -> None:
        _ = await _find(client)

        assert found.calls.last.request.url.params == httpx.QueryParams()

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_declined_call_is_retried_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_PATH).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json=_notebook_payload())]
        )

        _ = await _find(client)

        assert route.call_count == 2, (
            "getNotebookFromWebUrl is a read spelled as a POST, so the SDK's default retry runs"
        )


class TestWhatItAnswers:
    async def test_the_notebook_is_mapped_from_graph(
        self, client: GraphServiceClient, found: respx.Route
    ) -> None:
        answer = await _find(client)

        assert answer.uri == OnenoteNotebookHandle(NOTEBOOK_ID).uri
        assert answer.name == "Team Notebook"
        assert answer.is_default is True
        assert answer.is_shared is False
        assert answer.user_role == "Owner"
        assert answer.web_url == _WEB_URL
        assert answer.client_url == _CLIENT_URL
        assert answer.created_at is not None
        assert answer.last_modified_at is not None
        assert found.call_count == 1

    async def test_no_links_at_all_answers_null_addresses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(200, json=_notebook_payload(links=False))
        )

        answer = await _find(client)

        assert answer.web_url is None
        assert answer.client_url is None

    async def test_no_user_role_answers_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(200, json=_notebook_payload(user_role=None))
        )

        answer = await _find(client)

        assert answer.user_role is None


class TestGraphFailures:
    async def test_a_404_is_a_graph_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _find(client)

    async def test_a_403_is_a_graph_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "Forbidden"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _find(client)


class TestWhatItRefuses:
    async def test_a_notebook_handle_is_refused_before_any_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="needs no resolving"):
            _ = await _find(client, web_url=OnenoteNotebookHandle("1-ABC").uri)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "value",
        [
            OnenoteSectionGroupHandle("1-ABC").uri,
            OnenoteSectionHandle("1-ABC").uri,
            OnenotePageHandle("1-ABC!0").uri,
        ],
    )
    async def test_a_page_section_or_group_handle_is_refused_before_any_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="does not resolve it"):
            _ = await _find(client, web_url=value)

        assert len(graph.calls) == 0


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    finder.register(mcp, transport)
    tool = await mcp.get_tool(finder.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_read(self) -> None:
        assert finder.GRAPH_PERMISSIONS == ("Notes.Read",)

    def test_the_call_example_is_a_web_url(self) -> None:
        assert set(finder.GRAPH_CALL_EXAMPLE) == {"web_url"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(finder.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_one_argument_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"web_url"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, "a tool with no annotations joins the write surface"
        assert annotations.read_only_hint is READ_ONLY["readOnlyHint"]
