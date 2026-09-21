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
    OnenoteOperationHandle,
    OnenotePageHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
    onenote_operation_handle,
)
from office_365_mcp.shared.notes import OperationSummary
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import onenote_get_operation as getter
from office_365_mcp.tools.onenote_get_operation import get_operation

_OPERATION_ID = "1-SYNTHETICOPERATION0000!0-ABCDEF"

_OPERATION_URI = OnenoteOperationHandle(_OPERATION_ID).uri

_GET_PATH = f"/me/onenote/operations/{_OPERATION_ID}"


def _operation_payload(
    *,
    operation_id: str | None = _OPERATION_ID,
    status: str | None = "Running",
    percent_complete: str | None = "42",
    created: str | None = "2026-01-01T00:00:00Z",
    last_action: str | None = "2026-01-01T00:05:00Z",
    resource_location: str | None = None,
    resource_id: str | None = None,
    error: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": operation_id,
        "status": status,
        "percentComplete": percent_complete,
        "createdDateTime": created,
        "lastActionDateTime": last_action,
        "resourceLocation": resource_location,
        "resourceId": resource_id,
        "error": dict(error) if error is not None else None,
    }


def _gets(graph: respx.MockRouter, payload: Mapping[str, object]) -> respx.Route:
    return graph.get(_GET_PATH).mock(return_value=httpx.Response(200, json=dict(payload)))


async def _get(client: GraphServiceClient, *, operation: str = _OPERATION_URI) -> OperationSummary:
    return await get_operation(client, operation=operation)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    getter.register(mcp, transport)
    tool = await mcp.get_tool(getter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_reads_the_operation_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _gets(graph, _operation_payload())

        _ = await _get(client)

        assert route.call_count == 1
        assert len(graph.calls) == 1

    async def test_it_asks_for_no_query_parameters(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _gets(graph, _operation_payload())

        _ = await _get(client)

        assert dict(route.calls.last.request.url.params) == {}


class TestWhatItAnswers:
    async def test_every_field_maps_off_the_operation(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets(
            graph,
            _operation_payload(
                status="Running",
                percent_complete="55",
                created="2026-01-01T00:00:00Z",
                last_action="2026-01-01T00:05:00Z",
            ),
        )

        answer = await _get(client)

        assert answer.uri == _OPERATION_URI
        assert answer.status == "Running"
        assert answer.percent_complete == "55"
        assert answer.created_at is not None
        assert answer.created_at.isoformat() == "2026-01-01T00:00:00+00:00"
        assert answer.last_action_at is not None
        assert answer.last_action_at.isoformat() == "2026-01-01T00:05:00+00:00"

    async def test_a_completed_page_copy_names_a_page_result(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        page_id = "1-COPIEDPAGE0000000000000000000000!0-ABCDEF"
        _ = _gets(
            graph,
            _operation_payload(
                status="Completed",
                resource_location=(
                    "https://graph.microsoft.com/v1.0/users/me/onenote/pages/" + page_id
                ),
                resource_id=page_id,
            ),
        )

        answer = await _get(client)

        assert answer.status == "Completed"
        assert answer.result_uri == OnenotePageHandle(page_id).uri
        assert answer.result_kind == "page"

    async def test_a_completed_section_copy_names_a_section_result(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        section_id = "1-COPIEDSECTION00000000000000000!0-ABCDEF"
        _ = _gets(
            graph,
            _operation_payload(
                status="Completed",
                resource_location=(
                    "https://graph.microsoft.com/v1.0/users/me/onenote/sections/" + section_id
                ),
                resource_id=section_id,
            ),
        )

        answer = await _get(client)

        assert answer.result_uri == OnenoteSectionHandle(section_id).uri
        assert answer.result_kind == "section"

    async def test_a_completed_notebook_copy_names_a_notebook_result(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        notebook_id = "1-COPIEDNOTEBOOK000000000000000!0-ABCDEF"
        _ = _gets(
            graph,
            _operation_payload(
                status="Completed",
                resource_location=(
                    "https://graph.microsoft.com/v1.0/users/me/onenote/notebooks/" + notebook_id
                ),
                resource_id=notebook_id,
            ),
        )

        answer = await _get(client)

        assert answer.result_uri == OnenoteNotebookHandle(notebook_id).uri
        assert answer.result_kind == "notebook"

    async def test_a_running_operation_names_no_result(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets(graph, _operation_payload(status="Running", resource_location=None))

        answer = await _get(client)

        assert answer.result_uri is None
        assert answer.result_kind is None

    async def test_a_running_operation_can_already_show_a_high_percent_complete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets(graph, _operation_payload(status="Running", percent_complete="100"))

        answer = await _get(client)

        assert answer.status == "Running"
        assert answer.percent_complete == "100"

    async def test_a_failed_operation_carries_the_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets(
            graph,
            _operation_payload(
                status="Failed",
                error={"code": "20117", "message": "Notebook not found"},
            ),
        )

        answer = await _get(client)

        assert answer.status == "Failed"
        assert answer.error_code == "20117"
        assert answer.error_message == "Notebook not found"

    async def test_nulls_when_graph_names_none_of_them(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets(
            graph,
            _operation_payload(
                status=None,
                percent_complete=None,
                created=None,
                last_action=None,
                resource_location=None,
                resource_id=None,
                error=None,
            ),
        )

        answer = await _get(client)

        assert answer.status is None
        assert answer.percent_complete is None
        assert answer.created_at is None
        assert answer.last_action_at is None
        assert answer.result_uri is None
        assert answer.result_kind is None
        assert answer.error_code is None
        assert answer.error_message is None

    async def test_an_operation_with_no_id_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets(graph, _operation_payload(operation_id=None))

        with pytest.raises(AssertionError):
            _ = await _get(client)


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            OnenotePageHandle("PAGE1").uri,
            OnenoteSectionHandle("SECTION1").uri,
            OnenoteNotebookHandle("NOTEBOOK1").uri,
            OnenoteSectionGroupHandle("GROUP1").uri,
            "1-SYNTHETICOPERATION0000",
            "https://onenote.example.invalid/operation/1-SYNTHETICOPERATION0000",
            "",
            "   ",
            "onenote:///operations/",
            "onenote:///operations/%20",
        ],
    )
    async def test_a_value_that_is_not_an_operation_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError):
            _ = await _get(client, operation=value)

        assert len(graph.calls) == 0, "a refused handle reads nothing"

    async def test_the_refusal_names_the_tools_that_mint_an_operation_handle(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="onenote_copy_page"):
            _ = await _get(client, operation="not a handle")


class TestGraphFailures:
    async def test_a_404_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_GET_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _get(client)

    async def test_a_403_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_GET_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _get(client)

    async def test_the_call_example_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", getter.GRAPH_CALL_EXAMPLE)
        handle = onenote_operation_handle(example["operation"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own operation value is not a handle"
        route = graph.get(f"/me/onenote/operations/{handle.operation_id}").mock(
            return_value=httpx.Response(
                200, json=_operation_payload(operation_id=handle.operation_id)
            )
        )

        _ = await _get(client, operation=example["operation"])

        assert route.call_count == 1


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_read(self) -> None:
        assert getter.GRAPH_PERMISSIONS == ("Notes.Read",)

    def test_the_call_example_is_an_operation_handle(self) -> None:
        assert set(getter.GRAPH_CALL_EXAMPLE) == {"operation"}

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(getter.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_one_argument_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"operation"}

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

    async def test_the_description_names_the_statuses_and_the_copy_tools(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        for word in ("NotStarted", "Running", "Completed", "Failed"):
            assert word in description
        for tool_name in ("onenote_copy_page", "onenote_copy_section", "onenote_copy_notebook"):
            assert tool_name in description

    async def test_the_description_says_a_404_means_no_record_rather_than_an_expiry(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "no record of this operation" in description
        assert "expire" not in description
        assert "almost always" not in description

    async def test_the_description_says_percent_complete_is_not_the_completion_signal(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "percent_complete" in description
        assert "only `status` says" in description

    async def test_the_description_warns_the_returned_uri_can_differ_from_the_polled_handle(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = (tool.description or "").casefold()
        assert "not the one to reuse" in description

    def test_not_found_advice_points_at_the_listers(self) -> None:
        assert "onenote_list_pages" in getter.GRAPH_NOT_FOUND
        assert "onenote_list_sections" in getter.GRAPH_NOT_FOUND
        assert "onenote_list_notebooks" in getter.GRAPH_NOT_FOUND

    def test_not_found_advice_does_not_invent_an_expiry_or_a_base_rate(self) -> None:
        advice = getter.GRAPH_NOT_FOUND.casefold()
        assert "expire" not in advice
        assert "almost always" not in advice
