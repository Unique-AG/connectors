from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from msgraph.generated.users.item.onenote.notebooks.item.copy_notebook import (
    copy_notebook_post_request_body as _copy_notebook_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import (
    FetchedResponse,
    fetch_response,
    graph_errors,
    native_response,
    no_retry,
)
from office_365_mcp.shared.handles import onenote_notebook_handle
from office_365_mcp.shared.notes import OperationSummary, accepted_operation
from office_365_mcp.shared.seam import WRITE_ADDITIVE, graph_client_for_caller

TOOL_NAME = "onenote_copy_notebook"

STEP_COPY_NOTEBOOK = "copy_notebook"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

MAX_NEW_NAME_CHARACTERS = 128

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "notebook": "onenote:///notebooks/1-SYNTHETICNOTEBOOK0000"
}

_NOT_A_NOTEBOOK_HANDLE = (
    "onenote_copy_notebook takes a notebook handle in `notebook`. It looks like "
    + "onenote:///notebooks/{id}, and it comes from the `uri` of a onenote_list_notebooks or "
    + "onenote_find_notebook_from_url result. A section handle (onenote:///sections/{id}) and a "
    + "section group handle (onenote:///sectiongroups/{id}) are neither one a notebook handle. "
    + "Copy it word for word. This same value fails again, so do not retry it."
)

_NO_OPERATION_NAMED = (
    "Microsoft accepted this copy but named no operation to follow: the response carried "
    + "neither an operation in its body nor an Operation-Location header. The copy may still be "
    + "running with nothing here able to track it. Poll nothing; instead look for the result "
    + "with onenote_list_notebooks after a while, and do not call this tool again for the same "
    + "copy — that starts a second, independent one."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 could not start this copy. The handle is well formed, so the argument is not "
    + "the problem: the notebook was most likely deleted, or the signed-in user's access to it "
    + "was removed, since it was found. Find it again with onenote_list_notebooks or "
    + "onenote_find_notebook_from_url, and take a fresh `uri` from that result. This same handle "
    + "fails the same way every time, so do not retry it unchanged."
)

_DESCRIPTION = """\
Starts a copy of a whole notebook into the signed-in user's own OneDrive. This call does not copy \
the notebook itself: Microsoft runs the copy, and the answer is the operation that tracks it. \
Pass the answer's `uri` to onenote_get_operation until `status` reads Completed or Failed.

Notes:
- This tool asks nobody to agree, because the copy lands in the user's own OneDrive.
- If a call times out, do not call this tool again first: a second call starts a second copy. \
Before you call again, make sure that onenote_list_notebooks does not show the copy.
"""


async def copy_notebook(
    client: GraphServiceClient, *, notebook: str, new_name: str | None = None
) -> OperationSummary:
    handle = onenote_notebook_handle(notebook)
    if handle is None:
        raise ToolError(_NOT_A_NOTEBOOK_HANDLE)

    with graph_errors(TOOL_NAME, step=STEP_COPY_NOTEBOOK):
        fetched = await _copy(client, handle.notebook_id, new_name)

    summary = accepted_operation(fetched)
    if summary is None:
        raise ToolError(_NO_OPERATION_NAMED)
    return summary


async def _copy(
    client: GraphServiceClient, notebook_id: str, new_name: str | None
) -> FetchedResponse:
    builder = client.me.onenote.notebooks.by_notebook_id(notebook_id).copy_notebook
    request = RequestInformation(Method.POST, builder.url_template, builder.path_parameters)
    request.headers.try_add("Accept", "application/json")
    request.set_content_from_parsable(  # pyright: ignore[reportUnknownMemberType]
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        "application/json",
        _copy_notebook_body.CopyNotebookPostRequestBody(rename_as=new_name),
    )
    request.add_request_options([*no_retry(), *native_response()])
    return await fetch_response(client, request)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Copy a Notebook",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def onenote_copy_notebook(
        notebook: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The notebook to copy: the `uri` of a onenote_list_notebooks or "
                    + "onenote_find_notebook_from_url result, or a onenote_create_notebook answer, "
                    + "copied word for word. The shape is onenote:///notebooks/{id}."
                ),
            ),
        ],
        new_name: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=MAX_NEW_NAME_CHARACTERS,
                description=(
                    "A new name for the copy. Omit it to keep the notebook's own name. The name "
                    + "must be unique across the user's OneNote, at most 128 characters long, and "
                    + "must not contain any of these characters: ? * / : < > | ' \". Microsoft "
                    + "refuses a bad name and no copy starts."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> OperationSummary:
        return await copy_notebook(client, notebook=notebook, new_name=new_name)
