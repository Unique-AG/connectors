from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.drive_item import DriveItem
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphNotFound, graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.files import (
    ITEM_HANDLE_SOURCES,
    UNNAMED_FOLDER_LABEL,
    UNNAMED_ITEM_LABEL,
    item_for_a_question,
    parent_folder_label,
)
from office_365_mcp.shared.handles import DriveFolderHandle, drive_item_handle
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "sharepoint_delete_item"

STEP_DELETE = "delete_item"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.ReadWrite.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "item": "sharepoint:///files/b%21SYNTHETICDRIVE0000/01SYNTHETICFILE0000",
}

_DELETE = "delete"
_KEEP_THE_ITEM = "keep the item"
_NOTHING_DELETED = "The item was not moved to the recycle bin."

_DESCRIPTION = """\
Moves one file or one folder in OneDrive or SharePoint to the recycle bin, for the signed-in \
user. A folder goes to the recycle bin together with everything inside it. This connector never \
erases a file or a folder permanently. Get the handle from sharepoint_browse_folder or \
sharepoint_search_files. OneDrive and SharePoint can show the change to everyone who can open the \
folder.

Notes:
- This tool asks the user to agree before it changes anything, every time.
- This tool does not move the top folder of a drive.
- This call is safe to repeat after a timeout. A second call finds no item and reports that.
"""

_NOT_AN_ITEM_HANDLE = (
    "sharepoint_delete_item takes a file handle or a folder handle. A file handle looks like "
    + "sharepoint:///files/{drive_id}/{item_id}. A folder handle looks like "
    + "sharepoint:///folders/{drive_id}/{item_id}. Both ids are percent-encoded. A web address, "
    + "a path, a file name and a bare item id are not handles. "
    + ITEM_HANDLE_SOURCES
    + " The item was not moved to the recycle bin. This same value fails again, so do not retry "
    + "it."
)

_THE_DRIVE_ROOT = (
    "This handle names the top folder of a drive, and sharepoint_delete_item does not move that "
    + "folder to the recycle bin. The item was not moved to the recycle bin. To delete a file or "
    + "a folder inside the drive, pass the handle of that item. This same value fails again, so "
    + "do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 has no such file or folder to delete, and this call deleted nothing. The item "
    + "is probably already gone. A person or an earlier call deleted it, or somebody moved it to "
    + "another drive. An item in another drive needs a new handle.\n\n"
    + "If you must still delete the item, find it again with sharepoint_search_files or "
    + "sharepoint_browse_folder. Then use the `uri` from that new result. If the item is not in "
    + "that result, it is already gone and nothing is left to delete. The same handle fails the "
    + "same way, so do not retry it."
)


class DeletedItem(BaseModel):
    name: str | None = Field(
        description=(
            "The name of the file or folder immediately before the delete, with the extension "
            + "of a file. Null when Graph reported no name for the item."
        )
    )
    parent_uri: str | None = Field(
        description=(
            "The handle of the folder that held the item: sharepoint:///folders/{drive_id}/"
            + "{item_id}. Pass it to sharepoint_browse_folder to see what is left in that folder. "
            + "Null when Graph reported no parent folder."
        )
    )
    was_folder: bool = Field(
        description=(
            "True when the item was a folder, and false when it was a file. This tool read it "
            + "before the delete."
        )
    )
    deleted: Literal[True] = Field(
        description=(
            "Always true, because this tool answers only when the item is gone from its handle. "
            + "It is also true when the item was there at the start of this call, but Graph then "
            + "found no item to delete."
        )
    )


async def delete_item(
    client: GraphServiceClient, *, item: str, confirm: Confirm
) -> DeletedItem | InputRequiredResult:
    handle = drive_item_handle(item)
    if handle is None:
        raise ToolError(_NOT_AN_ITEM_HANDLE)

    about = write_state_for(TOOL_NAME, handle.drive_id, handle.item_id)
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        found = await item_for_a_question(client, handle.drive_id, handle.item_id)
        if found.root is not None:
            refused = _THE_DRIVE_ROOT
        else:
            with not_graph():
                answer = await confirm(_question(found), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with suppress(GraphNotFound), graph_step(STEP_DELETE):
                await (
                    client.drives.by_drive_id(handle.drive_id)
                    .items.by_drive_item_id(handle.item_id)
                    .delete(
                        request_configuration=RequestConfiguration[QueryParameters](
                            options=no_retry()
                        )
                    )
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return _answer(found, drive_id=handle.drive_id)


def _question(item: DriveItem) -> str:
    where = parent_folder_label(item)
    if item.folder is None:
        file = f"the file {item.name!r}" if item.name else UNNAMED_ITEM_LABEL
        return f"Move {file} from {where} to the recycle bin?"
    folder = f"the folder {item.name!r}" if item.name else UNNAMED_FOLDER_LABEL
    return (
        f"Move {folder} from {where} to the recycle bin, together with everything "
        + f"inside it?{_how_full(item.folder.child_count)}"
    )


def _how_full(child_count: int | None) -> str:
    if child_count is None:
        return ""
    if child_count == 0:
        return " The folder is empty."
    noun = "item" if child_count == 1 else "items"
    return f" It has {child_count} {noun} directly inside it."


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_DELETE, decline=_KEEP_THE_ITEM, nothing_happened=_NOTHING_DELETED
    )


def _answer(item: DriveItem, *, drive_id: str) -> DeletedItem:
    parent = item.parent_reference
    parent_id = parent.id if parent is not None else None
    return DeletedItem(
        name=item.name,
        parent_uri=None if parent_id is None else DriveFolderHandle(drive_id, parent_id).uri,
        was_folder=item.folder is not None,
        deleted=True,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Delete an Item",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def sharepoint_delete_item(
        item: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The file or folder to move to the recycle bin. A file handle and a folder "
                    + "handle both work. "
                    + ITEM_HANDLE_SOURCES
                    + " A web address, a path and a name are not handles."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedItem | InputRequiredResult:
        return await delete_item(client, item=item, confirm=a_person_agrees(ctx))
