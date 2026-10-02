from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from mcp.types import InputRequiredResult
from msgraph.generated.users.item.onenote.notebooks.item.copy_notebook import (
    copy_notebook_post_request_body as _copy_notebook_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import (
    FetchedResponse,
    fetch_response,
    graph_errors,
    graph_step,
    native_response,
    no_retry,
    not_graph,
)
from office_365_mcp.shared.handles import OnenoteNotebookHandle, onenote_notebook_handle
from office_365_mcp.shared.notes import (
    OperationSummary,
    accepted_operation,
    in_a_site,
    notebook_audience,
    onenote_root,
    write_state_for,
)
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    owner_refused,
    person_confirms,
)

TOOL_NAME = "onenote_copy_notebook"

STEP_COPY_NOTEBOOK = "copy_notebook"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("onenote_list_notebooks",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "notebook": "onenote:///notebooks/1-SYNTHETICNOTEBOOK0000"
}

_COPY = "copy"
_DO_NOT_COPY = "do not copy"
_NOTHING_COPIED = "Nothing was copied."

_UNNAMED_NOTEBOOK = "an unnamed notebook"
_OWN_ONEDRIVE = "your own OneDrive"

_HANDLE_OWNERS = (
    "A handle from a group notebook starts with onenote:///groups/{group}/ instead. This tool "
    + "refuses a handle from a site notebook, which starts with onenote:///sites/{site}/."
)

_NOT_A_NOTEBOOK_HANDLE = (
    "onenote_copy_notebook takes a notebook handle in `notebook`. It looks like "
    + "onenote:///notebooks/{id}, and it comes from the `uri` of a onenote_list_notebooks or "
    + "onenote_find_notebook_from_url result. "
    + _HANDLE_OWNERS
    + " A section handle (onenote:///sections/{id}) and a section group handle "
    + "(onenote:///sectiongroups/{id}) are neither one a notebook handle. Copy it word for word. "
    + "This same value fails again, so do not retry it."
)

_NO_OPERATION_NAMED = (
    "Microsoft accepted this copy but named no operation to follow: the response carried "
    + "neither an operation in its body nor an Operation-Location header. The copy may still be "
    + "running with nothing here able to track it. Poll nothing; instead look for the result "
    + "with onenote_list_notebooks after a while, and do not call this tool again for the same "
    + "copy — that starts a second, independent one."
)

_SITE_NOTEBOOK = (
    "onenote_copy_notebook cannot copy this notebook. Microsoft Graph documents no copy from or "
    + "into a notebook of a SharePoint site. This same call fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not start this copy. The `notebook` handle is well formed. Most likely, "
    + "the notebook was deleted, or the signed-in user lost access to it. Find it again with "
    + "onenote_list_notebooks or onenote_find_notebook_from_url, and take a fresh `uri` from that "
    + "result. If this call named a `to_group`, the id can also name no group that the user can "
    + "reach. Take that id from teams_list_my_teams, or ask the user for it. This same call fails "
    + "again, so do not retry it unchanged."
)

_OWNER_REFUSED = (
    "Microsoft 365 refused this request for the `to_group` that this call named. Most likely, the "
    + "signed-in user is not a member of that group, or the id is wrong. Ask the user for the "
    + "correct id, or ask them to get access. If this tool works without `to_group`, the "
    + "permissions of this connector are not the problem. If it fails without it too, ask a "
    + "Microsoft 365 administrator to grant the delegated permission Notes.Create. This same call "
    + "fails again, so do not retry it."
)

_DESCRIPTION = """\
Starts a copy of a whole notebook into the signed-in user's own OneDrive, or into a Microsoft 365 \
group with `to_group`. This tool cannot copy a notebook of a SharePoint site. This call does not \
copy the notebook itself: Microsoft runs the copy, and the answer is the operation that tracks it. \
Pass the answer's `uri` to onenote_get_operation until `status` reads Completed or Failed.

Notes:
- This tool asks the user to agree before it writes into a Microsoft 365 group. A copy into the \
user's own OneDrive starts without a question. The question names the group only by its id. \
Before you call this tool, tell the user which group that id names.
- If a call times out, do not call this tool again first: a second call starts a second copy. \
Before you call again, make sure that onenote_list_notebooks does not show the copy. If this call \
named a `to_group`, pass that id to onenote_list_notebooks as `group`.
"""


def _question(name: str | None, to_group: str | None, new_name: str | None) -> str:
    notebook = name or _UNNAMED_NOTEBOOK
    where = (
        _OWN_ONEDRIVE if to_group is None else f"the Microsoft 365 group with the id {to_group!r}"
    )
    renamed = f", renamed {new_name!r}" if new_name is not None else ""
    return f"Copy the notebook {notebook!r} into {where}{renamed}?"


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_COPY, decline=_DO_NOT_COPY, nothing_happened=_NOTHING_COPIED)


async def copy_notebook(
    client: GraphServiceClient,
    *,
    notebook: str,
    new_name: str | None = None,
    to_group: str | None = None,
    confirm: Confirm,
    answer_pending: bool = False,
) -> OperationSummary | InputRequiredResult:
    handle = onenote_notebook_handle(notebook)
    if handle is None:
        raise ToolError(_NOT_A_NOTEBOOK_HANDLE)
    if in_a_site(handle.owner):
        raise ToolError(_SITE_NOTEBOOK)

    about = write_state_for("copy_notebook", handle.uri, to_group or "", new_name or "")
    fetched: FetchedResponse | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with owner_refused(to_group is not None, _OWNER_REFUSED), graph_errors(TOOL_NAME):
        if answer_pending or to_group is not None:
            source = await notebook_audience(client, handle.notebook_id, owner=handle.owner)
            with not_graph():
                answer = await confirm(_question(source.name, to_group, new_name), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_COPY_NOTEBOOK):
                fetched = await _copy(client, handle, new_name, to_group)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert fetched is not None, "a copy neither asked about nor refused sent nothing"
    summary = accepted_operation(fetched, owner=handle.owner)
    if summary is None:
        raise ToolError(_NO_OPERATION_NAMED)
    return summary


async def _copy(
    client: GraphServiceClient,
    handle: OnenoteNotebookHandle,
    new_name: str | None,
    to_group: str | None,
) -> FetchedResponse:
    root = onenote_root(client, handle.owner)
    builder = root.notebooks.by_notebook_id(handle.notebook_id).copy_notebook
    request = RequestInformation(Method.POST, builder.url_template, builder.path_parameters)
    request.headers.try_add("Accept", "application/json")
    request.set_content_from_parsable(  # pyright: ignore[reportUnknownMemberType]
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        "application/json",
        _copy_notebook_body.CopyNotebookPostRequestBody(group_id=to_group, rename_as=new_name),
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
                    + "copied word for word. The shape is onenote:///notebooks/{id}. "
                    + _HANDLE_OWNERS
                ),
            ),
        ],
        ctx: Context,
        new_name: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "A new name for the copy. Omit it to keep the notebook's own name. The name "
                    + "must be unique among the notebooks where the copy lands, and it must not "
                    + "contain any of these characters: ? * / : < > | ' \". Microsoft refuses a "
                    + "bad name and no copy starts."
                ),
            ),
        ] = None,
        to_group: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The Microsoft 365 group or team that gets the copy, as its Graph id. A team "
                    + "id is a group id. Take it from teams_list_my_teams, or ask the user for it. "
                    + "Omit it to copy the notebook into the user's own OneDrive."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> OperationSummary | InputRequiredResult:
        return await copy_notebook(
            client,
            notebook=notebook,
            new_name=new_name,
            to_group=to_group,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
