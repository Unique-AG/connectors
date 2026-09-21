import json
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.tools import FunctionTool, Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphFailure, GraphForbidden
from office_365_mcp.shared.handles import OnenoteNotebookHandle
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import onenote_create_notebook as creator

_NOTEBOOKS_PATH = "/me/onenote/notebooks"

_NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK0001!0001"


def _notebook_payload(
    *,
    notebook_id: str | None = _NOTEBOOK_ID,
    name: str | None = "My Notebook",
    is_default: bool | None = True,
    is_shared: bool | None = False,
    user_role: str | None = "Owner",
    web_url: str | None = "https://onenote.example.invalid/notebooks/my-notebook",
    client_url: str | None = "onenote:https://onenote.example.invalid/notebooks/my-notebook",
    created_at: str | None = "2026-03-01T09:00:00Z",
) -> dict[str, object]:
    return {
        "id": notebook_id,
        "displayName": name,
        "isDefault": is_default,
        "isShared": is_shared,
        "userRole": user_role,
        "links": {
            "oneNoteWebUrl": {"href": web_url} if web_url is not None else None,
            "oneNoteClientUrl": {"href": client_url} if client_url is not None else None,
        },
        "createdDateTime": created_at,
    }


@pytest.fixture
def notebooks(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_NOTEBOOKS_PATH)


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> tuple[dict[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("dict[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_posts_a_display_name_and_nothing_else(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload()))

        _ = await creator.create_notebook(client, name="My Notebook")

        assert notebooks.call_count == 1
        assert _sent(notebooks)["displayName"] == "My Notebook"

    async def test_the_content_type_is_json(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload()))

        _ = await creator.create_notebook(client, name="My Notebook")

        assert notebooks.calls.last.request.headers["content-type"] == "application/json"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(503))

        with pytest.raises(GraphFailure):
            _ = await creator.create_notebook(client, name="My Notebook")

        assert notebooks.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItAnswers:
    async def test_the_answer_carries_the_new_notebooks_handle_and_fields(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(
            return_value=httpx.Response(
                201,
                json=_notebook_payload(
                    name="Stored Name", is_default=False, is_shared=False, user_role="Owner"
                ),
            )
        )

        answer = await creator.create_notebook(client, name="My Notebook")

        assert answer.uri == OnenoteNotebookHandle(_NOTEBOOK_ID).uri
        assert answer.name == "Stored Name"
        assert answer.is_default is False
        assert answer.is_shared is False
        assert answer.user_role == "Owner"
        assert answer.web_url == "https://onenote.example.invalid/notebooks/my-notebook"
        assert answer.client_url == "onenote:https://onenote.example.invalid/notebooks/my-notebook"
        assert answer.created_at is not None
        assert answer.created_at.isoformat() == "2026-03-01T09:00:00+00:00"

    async def test_the_answer_is_read_off_graph_and_never_echoes_the_argument(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(
            return_value=httpx.Response(201, json=_notebook_payload(name="Untouched by argument"))
        )

        answer = await creator.create_notebook(client, name="something else entirely")

        assert "something else entirely" not in answer.model_dump_json()
        assert answer.name == "Untouched by argument"

    async def test_nulls_when_graph_names_no_web_or_client_link(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(
            return_value=httpx.Response(201, json=_notebook_payload(web_url=None, client_url=None))
        )

        answer = await creator.create_notebook(client, name="My Notebook")

        assert answer.web_url is None
        assert answer.client_url is None

    async def test_a_create_that_names_no_id_is_a_programming_error(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload(notebook_id=None)))

        with pytest.raises(AssertionError):
            _ = await creator.create_notebook(client, name="My Notebook")


class TestGraphFailures:
    async def test_a_403_is_a_forbidden(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await creator.create_notebook(client, name="My Notebook")

    async def test_a_409_duplicate_name_is_a_generic_graph_failure(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(
            return_value=httpx.Response(
                409, json={"error": {"code": "20117", "message": "already exists"}}
            )
        )

        with pytest.raises(GraphFailure):
            _ = await creator.create_notebook(client, name="My Notebook")

    async def test_the_call_example_reaches_graph(
        self, client: GraphServiceClient, notebooks: respx.Route
    ) -> None:
        notebooks.mock(return_value=httpx.Response(201, json=_notebook_payload()))
        example = cast("dict[str, str]", creator.GRAPH_CALL_EXAMPLE)

        _ = await creator.create_notebook(client, name=example["name"])

        assert notebooks.call_count == 1


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_create(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("Notes.Create",)

    def test_the_call_example_is_a_name(self) -> None:
        assert set(creator.GRAPH_CALL_EXAMPLE) == {"name"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("dict[str, object]", parameters["properties"])
        assert set(creator.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_one_argument_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("dict[str, object]", parameters["properties"])
        assert set(properties) == {"name"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("dict[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_an_additive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)
        assert isinstance(tool, FunctionTool)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_it_never_asks_to_confirm(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "never asks" in description
        assert "unshared" in description

    async def test_the_description_lists_the_forbidden_characters(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        for character in "?*/:<>|'\"":
            assert character in description, f"{character!r} missing from the description"

    async def test_the_description_states_the_duplicate_name_failure_as_observed_not_guessed(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "confirmed on a test tenant" in description
        assert "most often comes back as" not in description
        assert "bad request" not in description
