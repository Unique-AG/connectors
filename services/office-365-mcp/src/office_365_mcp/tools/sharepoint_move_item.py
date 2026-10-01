from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.item_reference import ItemReference
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.files import (
    FOLDER_HANDLE_SOURCES,
    ITEM_HANDLE_SOURCES,
    UNNAMED_ITEM_LABEL,
    DriveItemSummary,
    folder_label,
    item_for_a_question,
    parent_folder_label,
    summary_after_write,
)
from office_365_mcp.shared.handles import (
    DriveFileHandle,
    DriveFolderHandle,
    drive_folder_handle,
    drive_item_handle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "sharepoint_move_item"

STEP_MOVE = "move_item"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.ReadWrite.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "item": "sharepoint:///files/b%21SYNTHETICDRIVE0000/01SYNTHETICFILE0000",
    "to_folder": "sharepoint:///folders/b%21SYNTHETICDRIVE0000/01SYNTHETICFOLDER000",
}

_MOVE = "move"
_DO_NOT_MOVE = "do not move"
_NOTHING_MOVED = "Nothing was moved."

_TO_A_DIFFERENT_DRIVE = (
    "To move an item to a different drive, copy it with sharepoint_copy_item. Use "
    + "sharepoint_delete_item on the original only after sharepoint_browse_folder shows the copy."
)

_DESCRIPTION = f"""\
Moves one file or folder into a different folder of the same drive, in OneDrive or SharePoint, \
for the signed-in user. The item keeps its name. To change the name, use sharepoint_rename_item. \
OneDrive and SharePoint can show the change to everyone who can open the folder.

Notes:
- This tool asks the user to agree before it changes anything, every time.
- This tool moves an item inside one drive only. {_TO_A_DIFFERENT_DRIVE}
- This call is safe to repeat after a timeout.
"""

_NOT_AN_ITEM_HANDLE = (
    "sharepoint_move_item takes a file handle or a folder handle in `item`. A file handle looks "
    + "like sharepoint:///files/{drive_id}/{item_id}. A folder handle looks like "
    + "sharepoint:///folders/{drive_id}/{item_id}. Both ids are percent-encoded. A web address, "
    + "a path, a name and a bare id are not handles. "
    + ITEM_HANDLE_SOURCES
    + " This same value fails again, so do not retry it."
)

_NOT_A_FOLDER_HANDLE = (
    "sharepoint_move_item takes a folder handle in `to_folder`. A folder handle looks like "
    + "sharepoint:///folders/{drive_id}/{item_id}, with both ids percent-encoded. A file handle "
    + "is not a folder handle, because a file cannot hold other items. A web address, a path and "
    + "a folder name are not handles either. "
    + FOLDER_HANDLE_SOURCES
    + " This same value fails again, so do not retry it."
)

_ANOTHER_DRIVE = (
    "Nothing was moved. `item` and `to_folder` are in two different drives, and this tool moves "
    + "an item inside one drive only. "
    + _TO_A_DIFFERENT_DRIVE
    + " This same pair of values fails again, so do not retry it."
)

_INTO_ITSELF = (
    "Nothing was moved. `item` and `to_folder` name the same item, and an item cannot move into "
    + "itself. Use the handle of a different folder in `to_folder`. This same pair of values fails "
    + "again, so do not retry it."
)

_THE_TOP_FOLDER_STAYS = (
    "Nothing was moved. `item` is the top folder of its drive, and the top folder of a drive "
    + "cannot move. To move what it holds, move each item inside it. This same value fails again, "
    + "so do not retry it."
)

_NOT_A_FOLDER = (
    "Nothing was moved. `to_folder` names an item that Microsoft 365 does not hold as a folder, "
    + "so it cannot hold other items. Take the `uri` of a folder from sharepoint_browse_folder, "
    + "and copy it word for word. This same value fails again, so do not retry it."
)

_ALREADY_THERE = (
    "Nothing was moved. The item is already in the folder that `to_folder` names, so no change "
    + "is necessary. If an earlier call moved the item, that move is complete. A call with the "
    + "same values gives this same answer."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return an item that this move needs, and nothing was moved. The "
    + "handles are well formed, so the arguments are not the problem. The file or the folder was "
    + "most probably deleted, or somebody moved it to a different drive. A handle names the drive "
    + "as well as the item, so an item in a different drive needs a new handle. Find the item and "
    + "the folder again with sharepoint_search_files or sharepoint_browse_folder. Then use the "
    + "`uri` values from that new result. If you call this tool again with the same arguments, "
    + "the call will fail the same way."
)

_MOVED_BUT_UNREAD = (
    "Microsoft 365 moved the item. Then this connector did not get a complete answer about the "
    + "item from Microsoft 365. Use sharepoint_browse_folder on `to_folder` to see the item in its "
    + "new folder. A second call to sharepoint_move_item with the same arguments makes no second "
    + "change."
)


class MovedItem(BaseModel):
    item: DriveItemSummary = Field(
        description=(
            "The item as Microsoft 365 holds it after the move. Its `parent_uri` is the handle "
            + "of the folder that holds the item now. Read the new location from here, not from "
            + "`to_folder`."
        )
    )
    previous_parent_uri: str | None = Field(
        description=(
            "The handle of the folder that held the item before the move. This tool read it "
            + "before the write. To move the item back, pass this value as `to_folder`. Null when "
            + "Graph reported no parent folder."
        )
    )


async def move_item(
    client: GraphServiceClient, *, item: str, to_folder: str, confirm: Confirm
) -> MovedItem | InputRequiredResult:
    moving, into = _handles(item, to_folder)

    moved: MovedItem | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        found = await item_for_a_question(client, moving.drive_id, moving.item_id)
        folder = await item_for_a_question(client, into.drive_id, into.item_id)
        refused = _unmovable(found, folder)
        if refused is None:
            about = write_state_for(TOOL_NAME, moving.drive_id, moving.item_id, _id_of(folder))
            with not_graph():
                answer = await confirm(_question(found, folder), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            moved = await _move(client, moving, found, folder)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert moved is not None, "a move neither asked about nor refused moved nothing"
    return moved


def _handles(
    item: str, to_folder: str
) -> tuple[DriveFileHandle | DriveFolderHandle, DriveFolderHandle]:
    moving = drive_item_handle(item)
    if moving is None:
        raise ToolError(_NOT_AN_ITEM_HANDLE)
    into = drive_folder_handle(to_folder)
    if into is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    if moving.drive_id != into.drive_id:
        raise ToolError(_ANOTHER_DRIVE)
    if moving.item_id == into.item_id:
        raise ToolError(_INTO_ITSELF)
    return moving, into


def _unmovable(found: DriveItem, folder: DriveItem) -> str | None:
    if found.root is not None:
        return _THE_TOP_FOLDER_STAYS
    if folder.folder is None:
        return _NOT_A_FOLDER
    parent = found.parent_reference
    if parent is not None and parent.id == _id_of(folder):
        return _ALREADY_THERE
    return None


def _id_of(item: DriveItem) -> str:
    assert item.id is not None, "Graph answered a drive item read with no id"
    return item.id


def _question(found: DriveItem, folder: DriveItem) -> str:
    name = repr(cut_for_a_question(found.name)) if found.name else UNNAMED_ITEM_LABEL
    return f"Move {name} from {parent_folder_label(found)} to {folder_label(folder)}?"


async def _move(
    client: GraphServiceClient,
    moving: DriveFileHandle | DriveFolderHandle,
    found: DriveItem,
    folder: DriveItem,
) -> MovedItem:
    with graph_step(STEP_MOVE):
        answered = await (
            client.drives.by_drive_id(moving.drive_id)
            .items.by_drive_item_id(moving.item_id)
            .patch(
                DriveItem(parent_reference=ItemReference(id=_id_of(folder))),
                request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
            )
        )
    summary = await summary_after_write(
        client, moving.drive_id, answered, item_id=moving.item_id, unread=_MOVED_BUT_UNREAD
    )
    return MovedItem(item=summary, previous_parent_uri=_previous_parent_uri(moving, found))


def _previous_parent_uri(
    moving: DriveFileHandle | DriveFolderHandle, found: DriveItem
) -> str | None:
    parent = found.parent_reference
    if parent is None or parent.id is None:
        return None
    return DriveFolderHandle(moving.drive_id, parent.id).uri


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_MOVE, decline=_DO_NOT_MOVE, nothing_happened=_NOTHING_MOVED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Move an Item",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def sharepoint_move_item(
        item: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The file or folder to move. A file handle and a folder handle both work. "
                    + ITEM_HANDLE_SOURCES
                    + " A web address, a path and a name are not handles."
                ),
            ),
        ],
        to_folder: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The folder to move the item into. "
                    + FOLDER_HANDLE_SOURCES
                    + " A file handle, a path and a web address are not folder handles."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> MovedItem | InputRequiredResult:
        return await move_item(client, item=item, to_folder=to_folder, confirm=a_person_agrees(ctx))
