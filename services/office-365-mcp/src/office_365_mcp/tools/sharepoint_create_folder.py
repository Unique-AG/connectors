from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.method import Method
from mcp.types import InputRequiredResult
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.folder import Folder
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import (
    graph_errors,
    graph_step,
    no_retry,
    not_graph,
    request_with_query,
)
from office_365_mcp.shared.files import (
    FAIL_ON_CONFLICT,
    FOLDER_HANDLE_SOURCES,
    NAME_RULES,
    DriveItemSummary,
    folder_label,
    item_for_a_question,
    summary_after_write,
    unusable_name,
)
from office_365_mcp.shared.handles import drive_folder_handle
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "sharepoint_create_folder"

STEP_CREATE_FOLDER = "create_folder"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.ReadWrite.All",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("sharepoint_browse_folder",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "parent": "sharepoint:///folders/b%21SYNTHETICDRIVE0000/01SYNTHETICFOLDER000",
    "name": "Synthetic folder",
}

_CREATE = "create"
_DO_NOT_CREATE = "do not create"
_NOTHING_CREATED = "No folder was created."

_DESCRIPTION = """\
This tool creates one new, empty folder inside `parent`, for the signed-in user. `parent` is a \
folder in OneDrive or in a SharePoint document library. To see what a folder holds, use \
sharepoint_browse_folder. The answer's `uri` is the handle of the new folder. OneDrive and \
SharePoint can show the change to everyone who can open the folder.

Notes:
- This tool asks the user to agree before it creates anything, every time.
- If a folder named `name` is already there, Microsoft refuses and creates nothing.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
sharepoint_browse_folder does not show a folder named `name`.
"""

_NOT_A_FOLDER_HANDLE = (
    "sharepoint_create_folder takes a folder handle in `parent`. A folder handle looks like "
    + "sharepoint:///folders/{drive_id}/{item_id}, with both ids percent-encoded, for example "
    + "sharepoint:///folders/b%21SYNTHETICDRIVE0000/01SYNTHETICFOLDER000. A file handle "
    + "(sharepoint:///files/...) is not a folder handle, because a file cannot hold a folder. A "
    + "folder name, a path, a web address and a bare item id are not handles either. "
    + FOLDER_HANDLE_SOURCES
    + " This same value fails again, so do not retry it."
)

_NOT_A_FOLDER = (
    "No folder was created, because the item in `parent` is not a folder. This tool creates a "
    + "folder only inside another folder. Use the `uri` of a row that sharepoint_browse_folder "
    + "shows with `is_folder` true. This same value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find the folder in `parent`, and this call created nothing. The handle "
    + "is well formed, so the folder is most likely deleted, or it moved to another drive. A move "
    + "to another drive gives a folder a new handle. Find the folder again with "
    + "sharepoint_search_files or sharepoint_browse_folder, and take the `uri` from that result. "
    + "This same handle fails the same way, so do not retry it."
)

_WRITTEN_BUT_UNREAD = (
    "Microsoft 365 created the folder. Then this connector did not receive the new folder from "
    + "Microsoft 365. Do not call sharepoint_create_folder again for this folder. Use "
    + "sharepoint_browse_folder on `parent` to find the new folder and its `uri`."
)


async def create_folder(
    client: GraphServiceClient, *, parent: str, name: str, confirm: Confirm
) -> DriveItemSummary | InputRequiredResult:
    assert len(name) >= 1, f"name is bounded by the schema, got {len(name)}"
    handle = drive_folder_handle(parent)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    unusable = unusable_name(name)
    if unusable is not None:
        raise ToolError(unusable)

    about = write_state_for(TOOL_NAME, handle.drive_id, handle.item_id, name)
    created: DriveItemSummary | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        found = await item_for_a_question(client, handle.drive_id, handle.item_id)
        assert found.id is not None, "Graph answered a drive item read with no id"
        if found.folder is None:
            refused = _NOT_A_FOLDER
        else:
            with not_graph():
                answer = await confirm(_question(name, found), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_CREATE_FOLDER):
                posted = await _post_folder(client, handle.drive_id, found.id, name=name)
            created = await summary_after_write(
                client,
                handle.drive_id,
                posted,
                item_id=None if posted is None else posted.id,
                unread=_WRITTEN_BUT_UNREAD,
            )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert created is not None, "a create neither asked about nor refused created nothing"
    return created


def _question(name: str, parent: DriveItem) -> str:
    return f"Create the folder {name!r} inside {folder_label(parent)}?"


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
    )


async def _post_folder(
    client: GraphServiceClient, drive_id: str, parent_id: str, *, name: str
) -> DriveItem | None:
    children = client.drives.by_drive_id(drive_id).items.by_drive_item_id(parent_id).children
    request = request_with_query(
        Method.POST, children.url_template, children.path_parameters, query=FAIL_ON_CONFLICT
    )
    request.headers.try_add("Accept", "application/json")
    request.set_content_from_parsable(  # pyright: ignore[reportUnknownMemberType]
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        "application/json",
        DriveItem(name=name, folder=Folder()),
    )
    request.add_request_options(no_retry())
    return await client.request_adapter.send_async(  # pyright: ignore[reportUnknownMemberType]
        request, DriveItem, {"XXX": ODataError}
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Folder",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def sharepoint_create_folder(
        parent: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The folder that gets the new folder. "
                    + FOLDER_HANDLE_SOURCES
                    + " A file handle, a path and a web address are not folder handles."
                ),
            ),
        ],
        name: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The name of the new folder, as the user writes it. "
                    + NAME_RULES
                    + " The answer's `name` is what Microsoft stored."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DriveItemSummary | InputRequiredResult:
        return await create_folder(client, parent=parent, name=name, confirm=a_person_agrees(ctx))
