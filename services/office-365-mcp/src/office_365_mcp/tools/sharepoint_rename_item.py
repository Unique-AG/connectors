from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.drive_item import DriveItem
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.files import (
    ITEM_HANDLE_SOURCES,
    NAME_RULES,
    DriveItemSummary,
    item_access_refused,
    item_for_a_question,
    item_label,
    parent_folder_label,
    summary_after_write,
    unusable_name,
)
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle, drive_item_handle
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "sharepoint_rename_item"

STEP_RENAME = "rename_item"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.ReadWrite.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "item": "sharepoint:///files/b%21SYNTHETICDRIVE0000/01SYNTHETICFILE0000",
    "name": "Synthetic plan.docx",
}

_RENAME = "rename"
_DO_NOT_RENAME = "do not rename"
_NOTHING_RENAMED = "The item was not renamed."

_DESCRIPTION = """\
Changes the name of one file or folder in OneDrive or SharePoint for the signed-in user. The item \
stays in the same folder. To move the item to another folder, use sharepoint_move_item. OneDrive \
and SharePoint can show the change to everyone who can open the folder.

Notes:
- This tool asks the user to agree before it changes anything, every time.
- Write the extension in `name`, for example `Plan.docx`. A name without it changes how the file \
opens.
- This call is safe to repeat after a timeout.
"""

_NOT_AN_ITEM_HANDLE = (
    "sharepoint_rename_item takes a file handle or a folder handle. A file handle looks like "
    + "sharepoint:///files/{drive_id}/{item_id}. A folder handle looks like "
    + "sharepoint:///folders/{drive_id}/{item_id}. Both ids are percent-encoded. A web address, "
    + "a path, a file name and a bare item id are not handles. "
    + ITEM_HANDLE_SOURCES
    + " This same value fails again, so do not retry it."
)

_THE_DRIVE_ROOT = (
    "This handle names the top folder of a drive, and sharepoint_rename_item does not rename that "
    + "folder. Nothing was changed. Rename a file or a folder inside the drive instead. This same "
    + "value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this item, and nothing was renamed. The handle is well formed, "
    + "so the argument is not the problem. The item was most probably deleted, or somebody moved "
    + "it to another drive. A handle names the drive as well as the item, so an item in another "
    + "drive needs a new handle. Find the item again with sharepoint_search_files or "
    + "sharepoint_browse_folder, and take the `uri` from that new result. The same handle fails "
    + "the same way, so do not retry it."
)

GRAPH_FORBIDDEN = item_access_refused(_NOTHING_RENAMED)

_WRITTEN_BUT_UNREAD = (
    "Microsoft 365 renamed the item. Then this connector did not receive the renamed item from "
    + "Microsoft 365. Use sharepoint_browse_folder on the folder that holds the item to see the "
    + "new name. A second call to sharepoint_rename_item with the same name sets the same name "
    + "again and makes no second change."
)


class RenamedItem(BaseModel):
    item: DriveItemSummary = Field(
        description=(
            "The file or folder as Microsoft 365 holds it right after the rename. It has the same "
            + "shape as one row of a sharepoint_browse_folder answer."
        )
    )
    previous_name: str | None = Field(
        description=(
            "The name that the item had immediately before the rename. This tool read it before "
            + "the write. Null when Graph did not report a name."
        )
    )


async def rename_item(
    client: GraphServiceClient, *, item: str, name: str, confirm: Confirm
) -> RenamedItem | InputRequiredResult:
    assert len(name) >= 1, f"name is bounded by the schema, got {len(name)}"
    handle = drive_item_handle(item)
    if handle is None:
        raise ToolError(_NOT_AN_ITEM_HANDLE)
    unusable = unusable_name(name)
    if unusable is not None:
        raise ToolError(unusable)

    about = write_state_for(TOOL_NAME, handle.drive_id, handle.item_id, name)
    renamed: DriveItemSummary | None = None
    previous_name: str | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        found = await item_for_a_question(client, handle.drive_id, handle.item_id)
        previous_name = found.name
        if found.root is not None:
            refused = _THE_DRIVE_ROOT
        else:
            with not_graph():
                answer = await confirm(_question(found, name), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            renamed = await _renamed(client, handle, name)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert renamed is not None, "a rename neither asked about nor refused renamed nothing"
    return RenamedItem(item=renamed, previous_name=previous_name)


def _question(item: DriveItem, name: str) -> str:
    return f"Rename {item_label(item)} to {name!r} in {parent_folder_label(item)}?"


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_RENAME, decline=_DO_NOT_RENAME, nothing_happened=_NOTHING_RENAMED
    )


async def _renamed(
    client: GraphServiceClient, handle: DriveFileHandle | DriveFolderHandle, name: str
) -> DriveItemSummary:
    with graph_step(STEP_RENAME):
        patched = await (
            client.drives.by_drive_id(handle.drive_id)
            .items.by_drive_item_id(handle.item_id)
            .patch(
                DriveItem(name=name),
                request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
            )
        )
    return await summary_after_write(
        client, handle.drive_id, patched, item_id=handle.item_id, unread=_WRITTEN_BUT_UNREAD
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Rename an Item",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def sharepoint_rename_item(
        item: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The file or folder to rename. A file handle and a folder handle both work. "
                    + ITEM_HANDLE_SOURCES
                    + " A web address, a path and a name are not handles."
                ),
            ),
        ],
        name: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The new name for the file or folder, as the user writes it. "
                    + NAME_RULES
                    + " The answer's `item.name` is what Microsoft stored. Read the new name from "
                    + "the answer, not from this argument."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> RenamedItem | InputRequiredResult:
        return await rename_item(client, item=item, name=name, confirm=a_person_agrees(ctx))
