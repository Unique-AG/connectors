from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.handles import onenote_operation_handle
from office_365_mcp.shared.notes import OperationSummary
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "onenote_get_operation"

STEP_OPERATION = "operation"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "operation": "onenote:///operations/1-SYNTHETICOPERATION0000"
}

_NOT_AN_OPERATION_HANDLE = (
    "onenote_get_operation takes an operation handle. It looks like onenote:///operations/{id}, "
    + "with the id percent-encoded, for example "
    + "onenote:///operations/1-SYNTHETICOPERATION0000. A page handle "
    + "(onenote:///pages/{id}), a section handle (onenote:///sections/{id}) and a notebook "
    + "handle (onenote:///notebooks/{id}) are none of them an operation handle: they name what a "
    + "copy reads from or, once it finishes, produces — never the copy itself. Take the `uri` "
    + "from a onenote_copy_page, onenote_copy_section or onenote_copy_notebook answer, and copy "
    + "it word for word. This same value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 has no record of this operation. That can mean the copy finished long ago "
    + "and Microsoft has since dropped it, or that this handle never named a real operation to "
    + "begin with — either way, this call did nothing wrong, and the handle is not malformed. "
    + "Polling the same handle again will not change this answer. Look for what the copy "
    + "produced with onenote_list_pages, onenote_list_sections or onenote_list_notebooks "
    + "instead. This same handle fails the same way every time, so do not call this tool again "
    + "for it."
)

_DESCRIPTION = """\
Polls a copy that onenote_copy_page, onenote_copy_section or onenote_copy_notebook started. Pass \
the `operation` handle from the copy tool's answer every time. The `uri` in this tool's own \
answer can differ and is not the one to reuse. `status` reads NotStarted, Running, Completed or \
Failed. `percent_complete` is informational, and only `status` says that a copy is done.

Notes:
- Call again a few seconds apart until `status` reads Completed, which fills `result_uri`, or \
Failed, which fills `error_code` and `error_message`.
- A 404 means Microsoft has no record of this operation: the copy is over, or the handle never \
named one. Look for the result with the list tools instead.
"""


async def get_operation(client: GraphServiceClient, *, operation: str) -> OperationSummary:
    handle = onenote_operation_handle(operation)
    if handle is None:
        raise ToolError(_NOT_AN_OPERATION_HANDLE)

    with graph_errors(TOOL_NAME, step=STEP_OPERATION):
        found = await client.me.onenote.operations.by_onenote_operation_id(
            handle.operation_id
        ).get()

    assert found is not None, "Graph answered an operation read with no operation"
    return OperationSummary.from_operation(found)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Get an Operation's Status",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def onenote_get_operation(
        operation: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The copy to poll: the `uri` of a onenote_copy_page, onenote_copy_section or "
                    + "onenote_copy_notebook answer, copied word for word. The shape is "
                    + "onenote:///operations/{id}. An operation id alone, with no connector scheme "
                    + "around it, reaches nothing."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> OperationSummary:
        return await get_operation(client, operation=operation)
