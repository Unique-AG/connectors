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

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
    onenote_notebook_handle,
)
from office_365_mcp.shared.notes import OperationSummary
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import onenote_copy_notebook as copier
from office_365_mcp.tools.onenote_copy_notebook import copy_notebook

_NOTEBOOK_ID = "1-SYNTHETICNOTEBOOK0000!0-ABCDEF"
_OPERATION_ID = "1-SYNTHETICOPERATION0000!0-ABCDEF"

_NOTEBOOK_URI = OnenoteNotebookHandle(_NOTEBOOK_ID).uri

_COPY_PATH = f"/me/onenote/notebooks/{_NOTEBOOK_ID}/copyNotebook"


def _operation_payload(
    *,
    operation_id: str | None = _OPERATION_ID,
    status: str | None = "Running",
) -> dict[str, object]:
    return {
        "id": operation_id,
        "status": status,
        "percentComplete": None,
        "createdDateTime": "2026-01-01T00:00:00Z",
        "lastActionDateTime": "2026-01-01T00:00:00Z",
        "resourceLocation": None,
        "resourceId": None,
        "error": None,
    }


def _operation_location(operation_id: str = _OPERATION_ID) -> str:
    return f"https://graph.microsoft.com/v1.0/me/onenote/operations/{operation_id}"


def _copies_with_body(
    graph: respx.MockRouter, *, status: int = 202, payload: Mapping[str, object] | None = None
) -> respx.Route:
    body = dict(payload) if payload is not None else _operation_payload()
    return graph.post(_COPY_PATH).mock(return_value=httpx.Response(status, json=body))


def _copies_with_header_only(
    graph: respx.MockRouter, *, status: int = 202, operation_id: str = _OPERATION_ID
) -> respx.Route:
    return graph.post(_COPY_PATH).mock(
        return_value=httpx.Response(
            status, content=b"", headers={"Operation-Location": _operation_location(operation_id)}
        )
    )


async def _copy(
    client: GraphServiceClient, *, notebook: str = _NOTEBOOK_URI, new_name: str | None = None
) -> OperationSummary:
    return await copy_notebook(client, notebook=notebook, new_name=new_name)


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    copier.register(mcp, transport)
    tool = await mcp.get_tool(copier.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_copies_the_notebook_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph)

        _ = await _copy(client)

        assert copy.call_count == 1
        assert len(graph.calls) == 1

    async def test_an_empty_body_is_sent_when_no_name_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph)

        _ = await _copy(client)

        assert _sent(copy) == {}

    async def test_a_new_name_is_sent_as_rename_as(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph)

        _ = await _copy(client, new_name="Renamed notebook")

        assert _sent(copy) == {"renameAs": "Renamed notebook"}

    async def test_no_group_site_or_folder_keys_are_ever_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph)

        _ = await _copy(client, new_name="Renamed notebook")

        sent = _sent(copy)
        assert "groupId" not in sent
        assert "siteId" not in sent
        assert "siteCollectionId" not in sent
        assert "notebookFolder" not in sent

    async def test_the_copy_content_type_is_json(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph)

        _ = await _copy(client)

        assert copy.calls.last.request.headers["content-type"] == "application/json"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_copy_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = graph.post(_COPY_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _copy(client)

        assert copy.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            OnenoteSectionHandle("SECTION1").uri,
            OnenoteSectionGroupHandle("GROUP1").uri,
            _NOTEBOOK_ID,
            "https://onenote.example.invalid/notebook/1-SYNTHETICNOTEBOOK0000",
            "My notebook",
            "",
            "   ",
            "onenote:///notebooks/",
            "onenote:///notebooks/%20",
        ],
    )
    async def test_a_value_that_is_not_a_notebook_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _copy(client, notebook=value)

        assert len(graph.calls) == 0, "a refused handle copies nothing"

    async def test_the_refusal_names_the_tools_that_mint_a_notebook_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_list_notebooks"):
            _ = await _copy(client, notebook="My notebook")
        with pytest.raises(ToolError, match="onenote_find_notebook_from_url"):
            _ = await _copy(client, notebook="My notebook")


class TestWhatItAnswers:
    async def test_the_answer_is_the_operation_graph_started_from_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _copies_with_body(
            graph,
            payload=_operation_payload(operation_id="1-OPERATION0000!0-ABCDEF", status="Running"),
        )

        answer = await _copy(client)

        assert answer.status == "Running"
        assert "1-OPERATION0000" in answer.uri

    async def test_an_empty_202_with_only_the_operation_location_header_mints_the_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = _copies_with_header_only(graph, operation_id="1-HEADERONLY0000!0-ABCDEF")

        answer = await _copy(client)

        assert copy.call_count == 1
        assert "1-HEADERONLY0000" in answer.uri
        assert answer.status is None

    async def test_a_body_and_a_header_together_are_answered_from_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        body = _operation_payload(operation_id="1-FROMBODY0000!0-ABCDEF", status="Running")
        _ = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                202,
                json=body,
                headers={"Operation-Location": _operation_location("1-FROMHEADER0000!0-ABCDEF")},
            )
        )

        answer = await _copy(client)

        assert "1-FROMBODY0000" in answer.uri
        assert "1-FROMHEADER0000" not in answer.uri

    async def test_an_empty_202_with_neither_a_body_nor_a_header_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        copy = graph.post(_COPY_PATH).mock(return_value=httpx.Response(202, content=b""))

        with pytest.raises(ToolError, match="named no operation"):
            _ = await _copy(client)

        assert copy.call_count == 1, "the copy was still sent before this tool gave up on it"

    async def test_a_body_with_no_id_and_no_header_is_the_same_refusal_as_an_empty_202(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _copies_with_body(graph, payload=_operation_payload(operation_id=None))

        with pytest.raises(ToolError, match="named no operation"):
            _ = await _copy(client)


class TestGraphFailures:
    async def test_a_404_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _copy(client)

    async def test_a_403_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_COPY_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _copy(client)

    async def test_the_call_example_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", copier.GRAPH_CALL_EXAMPLE)
        handle = onenote_notebook_handle(example["notebook"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own notebook value is not a handle"
        route = graph.post(f"/me/onenote/notebooks/{handle.notebook_id}/copyNotebook").mock(
            return_value=httpx.Response(
                202,
                content=b"",
                headers={"Operation-Location": _operation_location(handle.notebook_id)},
            )
        )

        _ = await _copy(client, notebook=example["notebook"])

        assert route.call_count == 1

    def test_not_found_advice_points_at_the_finders(self) -> None:
        assert "onenote_list_notebooks" in copier.GRAPH_NOT_FOUND
        assert "onenote_find_notebook_from_url" in copier.GRAPH_NOT_FOUND


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_create(self) -> None:
        assert copier.GRAPH_PERMISSIONS == ("Notes.Create",)

    def test_the_call_example_is_a_notebook_handle(self) -> None:
        assert set(copier.GRAPH_CALL_EXAMPLE) == {"notebook"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(copier.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_two_arguments_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"notebook", "new_name"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

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

    async def test_the_description_says_no_confirmation_is_asked(
        self, transport: httpx.AsyncClient
    ) -> None:
        """The pinned phrase "asks nobody to confirm it" became the STE "asks nobody to agree,"
        and the retry warning now reads as guidance rather than "not safe to retry blindly," but
        both keep their original guarantee."""
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "asks nobody to agree" in description
        assert "do not call this tool again first" in description
        assert "onenote_get_operation" in description

    async def test_the_new_name_description_states_the_documented_naming_rule(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)
        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        new_name = cast("Mapping[str, object]", properties["new_name"])
        description = cast("str", new_name["description"])
        assert "128" in description
        assert "400" not in description
        assert "409" not in description
