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
Start copying an entire OneNote notebook — every section, section group and page in it — into \
the signed-in user's own OneDrive. Pass the `notebook` handle from a onenote_list_notebooks or \
onenote_find_notebook_from_url result. `new_name` renames the copy; omit it and Microsoft names \
the copy the same as the notebook it copied. This call does NOT copy the notebook itself: \
Microsoft Graph runs the copy on its own side, and this tool's answer is the operation that \
tracks it, not the copied notebook. Pass the answer's `uri` to onenote_get_operation, a few \
seconds apart, until `status` reads Completed — its `result_uri` is then the new notebook's \
handle — or Failed, whose `error_code` and `error_message` say why. The copy always lands in \
the user's own OneDrive, under their own account, so this tool asks nobody to confirm it: \
nothing this call does can become visible to somebody else purely by running it, even when the \
notebook being copied is one this user does not own or that others can see. This call is NOT \
SAFE TO RETRY BLINDLY: if it times out, a copy may already be running on Microsoft's side, and \
calling this tool again with the same arguments starts a second, independent copy of the whole \
notebook, sections and pages included. On a timeout, nothing came back to poll: list the user's \
notebooks with onenote_list_notebooks and look for one with this notebook's name (or \
`new_name`, if one was given) before calling again — Microsoft's index can lag a copy just as \
it lags a create.\
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
                    "The handle of the notebook to copy, from the `uri` of a "
                    + "onenote_list_notebooks or onenote_find_notebook_from_url result. The "
                    + "shape is onenote:///notebooks/{id}. Copy it word for word."
                ),
            ),
        ],
        new_name: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=MAX_NEW_NAME_CHARACTERS,
                description=(
                    "A new name for the copy. Omit it to keep the notebook's own name. "
                    + "Notebook names must be unique for this user, take at most 128 "
                    + "characters, and cannot contain any of these characters: "
                    + "? * / : < > | ' \". Microsoft refuses a name that breaks either rule, "
                    + "and this tool forwards that refusal."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> OperationSummary:
        return await copy_notebook(client, notebook=notebook, new_name=new_name)
