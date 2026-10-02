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
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
)
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import onenote_find_notebook_from_url as finder

NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK0000!0001"
GROUP_ID = "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d"

_WEB_URL = "https://onenote.example.invalid/notebooks/team-notebook"
_CLIENT_URL = "onenote:https://onenote.example.invalid/notebooks/team-notebook"

_PATH = "/me/onenote/notebooks/getNotebookFromWebUrl"
_GROUP_PATH = f"/groups/{GROUP_ID}/onenote/notebooks/getNotebookFromWebUrl"


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


@pytest.fixture
def found_for_a_group(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_GROUP_PATH).mock(return_value=httpx.Response(200, json=_notebook_payload()))


async def _find(
    client: GraphServiceClient, *, web_url: str = _WEB_URL, group: str | None = None
) -> finder.FoundNotebook:
    return await finder.find_notebook_from_url(client, web_url=web_url, group=group)


class TestWhatItAsks:
    async def test_it_sends_the_web_url_verbatim_in_the_body(
        self, client: GraphServiceClient, found: respx.Route
    ) -> None:
        _ = await _find(client)

        sent = cast("dict[str, object]", json.loads(found.calls.last.request.content))
        assert sent == {"webUrl": _WEB_URL}

    async def test_a_very_long_web_url_reaches_graph(
        self, client: GraphServiceClient, found: respx.Route
    ) -> None:
        long_url = f"{_WEB_URL}?{'a' * 5000}"

        _ = await _find(client, web_url=long_url)

        sent = cast("dict[str, object]", json.loads(found.calls.last.request.content))
        assert sent == {"webUrl": long_url}

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


class TestTheGroupRoute:
    async def test_a_group_asks_that_groups_route_and_never_the_users(
        self, client: GraphServiceClient, found: respx.Route, found_for_a_group: respx.Route
    ) -> None:
        _ = await _find(client, group=GROUP_ID)

        assert found_for_a_group.call_count == 1
        assert found.call_count == 0

    async def test_no_group_asks_the_users_route_and_never_a_groups(
        self, client: GraphServiceClient, found: respx.Route, found_for_a_group: respx.Route
    ) -> None:
        _ = await _find(client)

        assert found.call_count == 1
        assert found_for_a_group.call_count == 0

    async def test_the_group_route_sends_the_same_body_and_no_query_parameters(
        self, client: GraphServiceClient, found_for_a_group: respx.Route
    ) -> None:
        _ = await _find(client, group=GROUP_ID)

        request = found_for_a_group.calls.last.request
        assert cast("dict[str, object]", json.loads(request.content)) == {"webUrl": _WEB_URL}
        assert request.url.params == httpx.QueryParams()
        assert request.headers["accept"] == "application/json"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_declined_group_call_is_retried_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_GROUP_PATH).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json=_notebook_payload())]
        )

        _ = await _find(client, group=GROUP_ID)

        assert route.call_count == 2

    @pytest.mark.usefixtures("found_for_a_group")
    async def test_the_minted_handle_carries_the_group(self, client: GraphServiceClient) -> None:
        answer = await _find(client, group=GROUP_ID)

        assert (
            answer.uri
            == OnenoteNotebookHandle(NOTEBOOK_ID, owner=OnenoteOwner("groups", GROUP_ID)).uri
        )
        assert answer.uri.startswith(f"onenote:///groups/{GROUP_ID}/notebooks/")

    @pytest.mark.usefixtures("found")
    async def test_the_minted_handle_of_a_call_with_no_group_names_no_group(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _find(client)

        assert answer.uri == OnenoteNotebookHandle(NOTEBOOK_ID).uri
        assert "/groups/" not in answer.uri

    @pytest.mark.usefixtures("found_for_a_group")
    async def test_the_rest_of_the_answer_is_mapped_as_for_the_user(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _find(client, group=GROUP_ID)

        assert answer.name == "Team Notebook"
        assert answer.web_url == _WEB_URL
        assert answer.client_url == _CLIENT_URL

    async def test_a_404_on_the_group_route_is_a_graph_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_GROUP_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _find(client, group=GROUP_ID)

    def test_the_not_found_advice_names_the_group_and_keeps_the_retry_warning(self) -> None:
        assert "`group`" in finder.GRAPH_NOT_FOUND
        assert "fails again" in finder.GRAPH_NOT_FOUND


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

    async def test_a_group_notebook_handle_is_refused_before_any_graph_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        handle = OnenoteNotebookHandle("1-ABC", owner=OnenoteOwner("groups", GROUP_ID)).uri

        with pytest.raises(ToolError, match="needs no resolving"):
            _ = await _find(client, web_url=handle, group=GROUP_ID)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "value",
        [
            OnenoteSectionGroupHandle("1-ABC").uri,
            OnenoteSectionHandle("1-ABC").uri,
            OnenotePageHandle("1-ABC!0").uri,
            OnenoteSectionGroupHandle("1-ABC", owner=OnenoteOwner("groups", GROUP_ID)).uri,
            OnenoteSectionHandle("1-ABC", owner=OnenoteOwner("groups", GROUP_ID)).uri,
            OnenotePageHandle("1-ABC!0", owner=OnenoteOwner("groups", GROUP_ID)).uri,
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

    async def test_it_takes_the_web_address_and_the_group_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"web_url", "group"}

    async def test_only_the_web_address_is_required(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        assert parameters["required"] == ["web_url"]

    async def test_the_group_argument_says_whose_notebook_the_address_opens(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        described = cast("str", properties["group"]["description"])
        assert described.startswith(
            "The Microsoft 365 group or team whose notebook this address opens"
        )
        assert "A team id is a group id." in described
        assert "Take it from teams_list_my_teams, or ask the user for it." in described
        assert 15 <= len(described.split()) <= 60

    async def test_the_description_has_a_lead_with_the_sibling_and_notes_with_the_group_bullet(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        bullets = [line for line in notes.splitlines() if line.startswith("- ")]
        assert separator, "the description has no Notes section"
        assert 45 <= len(description.split()) <= 210
        assert 1 <= len(bullets) <= 3
        assert "onenote_list_recent_notebooks" in lead
        assert any("Pass `group`" in bullet for bullet in bullets)

    def test_the_answer_handle_says_how_a_group_notebook_handle_starts(self) -> None:
        described = finder.FoundNotebook.model_fields["uri"].description or ""
        assert "starts with onenote:///groups/{group}/" in described

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
