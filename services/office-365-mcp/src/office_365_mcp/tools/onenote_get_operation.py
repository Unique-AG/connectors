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
    "Microsoft 365 has no record of this operation. An operation id is not permanent: Microsoft "
    + "expires it once the copy it tracked has been done, or gone, for a while, and answers a "
    + "plain 404 rather than a Failed status from then on. So this almost always means the copy "
    + "finished long ago, or never started — not that this call did anything wrong, and not that "
    + "the handle is malformed. Look for what the copy produced with onenote_list_pages, "
    + "onenote_list_sections or onenote_list_notebooks instead. This same handle fails the same "
    + "way every time, so do not call this tool again for it."
)

_DESCRIPTION = """\
Poll the status of a copy this connector already started: onenote_copy_page, \
onenote_copy_section or onenote_copy_notebook. Pass the `operation` handle from one of those \
tools' answers. `status` is Microsoft's own word for where the copy stands: NotStarted, \
Running, Completed or Failed. Call this again a few seconds after the last call rather than in \
a tight loop, and keep calling it until `status` reads Completed or Failed — there is no push \
notification for a copy finishing. Once `status` reads Completed, `result_uri` is the handle of \
whatever the copy produced, and `result_kind` says which of a page, a section or a notebook it \
is: pass a page's `result_uri` to onenote_read_page, a section's to onenote_list_pages, and a \
notebook's to onenote_list_sections. Once `status` reads Failed, `error_code` and \
`error_message` carry what Microsoft said went wrong, and this tool has nothing further to add: \
find out what happened by reading those two fields rather than calling this tool again. An \
operation id expires once its copy has been done, or gone, for a while — Microsoft Graph then \
answers this call with a plain 404 instead of a Failed status. That 404 means the copy is over, \
one way or another, not that this call was wrong: look for the result with onenote_list_pages, \
onenote_list_sections or onenote_list_notebooks instead of retrying this tool for the same \
handle.\
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
    summary = OperationSummary.from_operation(found)
    assert summary is not None, "Graph answered an operation read with an operation that has no id"
    return summary


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
                    "The handle of the copy to poll, from the `uri` of a onenote_copy_page, "
                    + "onenote_copy_section or onenote_copy_notebook answer, copied word for "
                    + "word. The shape is onenote:///operations/{id}. Never build one yourself: "
                    + "an operation id alone, without this connector's scheme around it, reaches "
                    + "nothing."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> OperationSummary:
        return await get_operation(client, operation=operation)
