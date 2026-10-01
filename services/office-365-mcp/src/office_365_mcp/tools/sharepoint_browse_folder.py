from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.drives.item.items.item.children.children_request_builder import (
    ChildrenRequestBuilder,
)
from msgraph.generated.models.drive_item_collection_response import DriveItemCollectionResponse
from msgraph.generated.users.item.drive.drive_request_builder import DriveRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors, graph_step
from office_365_mcp.shared.files import ITEM_FIELDS, DriveItemSummary
from office_365_mcp.shared.handles import DriveFolderHandle, drive_folder_handle
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "sharepoint_browse_folder"

STEP_MY_DRIVE = "my_drive"
STEP_CHILDREN = "folder_children"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this folder. The handle is well formed, so the folder was "
    + "most likely deleted. It can also have moved to another drive, which gives it a new "
    + "handle. Find the folder again: search for it, or browse to it from a level above, and "
    + "take the `uri` that comes back with it. Use that new handle. Calling this tool again with "
    + "this handle fails in the same way."
)

_ROOT_ITEM = "root"

_DRIVE_FIELDS: tuple[str, ...] = ("id",)

_ChildrenQuery = ChildrenRequestBuilder.ChildrenRequestBuilderGetQueryParameters
_DriveQuery = DriveRequestBuilder.DriveRequestBuilderGetQueryParameters

OrderBy = Literal["name", "last_modified", "created", "size"]

_MISSING = float("-inf")

_DESCRIPTION = """\
This tool lists every item directly inside one folder in OneDrive or SharePoint. It lists one \
level only, and does not list items inside subfolders. You can use this tool to look through \
the contents of a specific folder. The tool `sharepoint_search_files` finds files by name or by \
content, across all of OneDrive and SharePoint. But it reaches only content that is in the \
search index. If the user names one folder and wants everything in it, indexed or not, use \
this tool instead.

Notes:
- Without `order_by`, this tool returns items in the order that Microsoft returns them. With \
`order_by`, this tool reads up to 1000 items of the level, sorts them, and then applies `limit`.
- If the level holds more than 1000 items, `order_covers_level` is false. Then the order applies \
to the first 1000 items that Microsoft returned and not to the whole level.
"""

_NOT_A_FOLDER_HANDLE = (
    "sharepoint_browse_folder takes a folder handle. It looks like "
    + "sharepoint:///folders/{driveId}/{itemId}, and it comes from the `uri` of an earlier "
    + "result. Copy it exactly. A folder name is not a handle. Nor is a path, nor a web address, "
    + "nor a bare item id. A file handle is not one either, because a file holds nothing to "
    + "browse. Omit `folder` to browse the top of the user's own OneDrive."
)


class DriveFolderLevel(BaseModel):
    """One level of one folder: what sits directly inside it, and whether a cap stopped the list."""

    items: list[DriveItemSummary] = Field(
        description=(
            "The files and folders inside the folder, in the order that Microsoft returned them "
            + "or that `order_by` names. A folder entry can hold more items than this list "
            + "shows. Call this tool again with its `uri` to reach them. An empty list means "
            + "that the folder holds nothing. This tool leaves out an item that Graph reports "
            + "with no drive."
        )
    )
    capped: bool = Field(
        description=(
            "This value is true when `limit` or the cap of 1000 items stops the list before "
            + "this level ends. To get more of the list, raise `limit` up to 1000. When the "
            + "level ends on its own, this value is false. This value says nothing about the "
            + "items inside a folder, because this call never looks inside one."
        )
    )
    order_covers_level: bool | None = Field(
        description=(
            "Null when `order_by` is not set. With `order_by`, this value is true when the "
            + "read reached the end of the level. Then the order holds for the whole level. "
            + "This value is false when the read stopped at 1000 items. Then an item that this "
            + "tool did not read can belong earlier in the order."
        )
    )


async def browse_folder(
    client: GraphServiceClient,
    *,
    folder: str | None = None,
    limit: int,
    order_by: OrderBy | None = None,
) -> DriveFolderLevel:
    assert limit >= 1, f"limit must be at least 1, got {limit}"
    handle = _folder_to_browse(folder)
    top, read = (limit, limit) if order_by is None else (None, MAX_SCANNED_ITEMS)

    with graph_errors(TOOL_NAME):
        target = await _my_drive_root(client) if handle is None else handle
        with graph_step(STEP_CHILDREN):
            first_page = await _children(client, target, top=top)
            assert first_page is not None, "Graph answered a folder listing with no collection"
            collected = await collect_pages(first_page, client, limit=read)

    rows = [
        row for item in collected.items if (row := DriveItemSummary.from_item(item)) is not None
    ]
    if order_by is None:
        return DriveFolderLevel(items=rows, capped=collected.capped, order_covers_level=None)
    ordered = _ordered(rows, order_by)
    return DriveFolderLevel(
        items=ordered[:limit],
        capped=collected.capped or len(ordered) > limit,
        order_covers_level=not collected.capped,
    )


def _ordered(rows: list[DriveItemSummary], order_by: OrderBy) -> list[DriveItemSummary]:
    by_name = sorted(rows, key=_name_key)
    if order_by == "name":
        return by_name
    return sorted(by_name, key=_DESCENDING_KEYS[order_by], reverse=True)


def _name_key(row: DriveItemSummary) -> tuple[bool, str]:
    return (row.name is None, (row.name or "").casefold())


def _timestamp(moment: datetime | None) -> float:
    return _MISSING if moment is None else moment.timestamp()


_DESCENDING_KEYS: Mapping[str, Callable[[DriveItemSummary], float]] = {
    "last_modified": lambda row: _timestamp(row.last_modified_at),
    "created": lambda row: _timestamp(row.created_at),
    "size": lambda row: _MISSING if row.size is None else row.size,
}


def _folder_to_browse(folder: str | None) -> DriveFolderHandle | None:
    if folder is None:
        return None
    handle = drive_folder_handle(folder)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    return handle


async def _my_drive_root(client: GraphServiceClient) -> DriveFolderHandle:
    with graph_step(STEP_MY_DRIVE):
        drive = await client.me.drive.get(
            request_configuration=RequestConfiguration[_DriveQuery](
                query_parameters=_DriveQuery(select=list(_DRIVE_FIELDS))
            )
        )
    assert drive is not None and drive.id is not None, "Graph returned no id for the user's drive"
    return DriveFolderHandle(drive.id, _ROOT_ITEM)


async def _children(
    client: GraphServiceClient, folder: DriveFolderHandle, *, top: int | None
) -> DriveItemCollectionResponse | None:
    return (
        await client.drives.by_drive_id(folder.drive_id)
        .items.by_drive_item_id(folder.item_id)
        .children.get(
            request_configuration=RequestConfiguration[_ChildrenQuery](
                query_parameters=_ChildrenQuery(select=list(ITEM_FIELDS), top=top)
            )
        )
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Browse Files",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def sharepoint_browse_folder(
        folder: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The folder to look inside. Take the `uri` of a folder or the `parent_uri` "
                    + "of an item from sharepoint_browse_folder or sharepoint_search_files. The "
                    + "`root_uri` of a drive from sharepoint_list_drives is a folder handle too. "
                    + "A name, a path and a web address are not handles. Omit it to browse the "
                    + "top of the signed-in user's own OneDrive."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "How many items to return from this level. This "
                    + "limit applies to this level only. If you raise it, this tool still does "
                    + "not reach items inside a nested folder."
                ),
            ),
        ] = 50,
        order_by: Annotated[
            OrderBy | None,
            Field(
                description=(
                    "How to sort this level. `name` sorts A to Z. `last_modified` and `created` "
                    + "list the newest item first. `size` lists the largest item first. An item "
                    + "with no value for the key comes last. Equal values sort by name. Omit this "
                    + "argument to keep the order that Microsoft returns."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> DriveFolderLevel:
        return await browse_folder(client, folder=folder, limit=limit, order_by=order_by)
