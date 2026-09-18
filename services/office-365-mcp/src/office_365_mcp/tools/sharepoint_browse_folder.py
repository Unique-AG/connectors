from collections.abc import Mapping
from typing import Annotated

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

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
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

MAX_ITEMS = 200

_ROOT_ITEM = "root"

_DRIVE_FIELDS: tuple[str, ...] = ("id",)

_ChildrenQuery = ChildrenRequestBuilder.ChildrenRequestBuilderGetQueryParameters
_DriveQuery = DriveRequestBuilder.DriveRequestBuilderGetQueryParameters

_DESCRIPTION = """\
This tool lists every item directly inside one folder in OneDrive or SharePoint. It lists one \
level only, and does not list items inside subfolders. You can use this tool to look through \
the contents of a specific folder. The tool `sharepoint_search_files` finds files by name or by \
content, across all of OneDrive and SharePoint. But it reaches only content that is in the \
search index. If the user names one folder and wants everything in it, indexed or not, use \
this tool instead.\
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
            "The files and folders directly inside the folder, in the order Microsoft returned "
            + "them. A folder entry here can hold further items that are not included. Call "
            + "this tool again with that entry's `uri` to reach them. An empty list means that "
            + "the folder holds nothing. This tool leaves out an item that Graph reports with "
            + "no drive, because this tool cannot address that item again."
        )
    )
    capped: bool = Field(
        description=(
            "When `limit` stops the list before this level ends, this value is true. To get "
            + "more of the list, raise `limit`. When the level ends on its own, this value is "
            + "false. This value says nothing about the items inside a folder that this call "
            + "returned. This call never looks inside such a folder."
        )
    )


async def browse_folder(
    client: GraphServiceClient, *, folder: str | None = None, limit: int
) -> DriveFolderLevel:
    assert 1 <= limit <= MAX_ITEMS, f"limit must be within 1..{MAX_ITEMS}, got {limit}"
    handle = _folder_to_browse(folder)

    with graph_errors(TOOL_NAME):
        target = await _my_drive_root(client) if handle is None else handle
        with graph_step(STEP_CHILDREN):
            first_page = await _children(client, target, limit=limit)
            assert first_page is not None, "Graph answered a folder listing with no collection"
            collected = await collect_pages(first_page, client, limit=limit)

    return DriveFolderLevel(
        items=[
            row for item in collected.items if (row := DriveItemSummary.from_item(item)) is not None
        ],
        capped=collected.capped,
    )


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
    client: GraphServiceClient, folder: DriveFolderHandle, *, limit: int
) -> DriveItemCollectionResponse | None:
    return (
        await client.drives.by_drive_id(folder.drive_id)
        .items.by_drive_item_id(folder.item_id)
        .children.get(
            request_configuration=RequestConfiguration[_ChildrenQuery](
                query_parameters=_ChildrenQuery(select=list(ITEM_FIELDS), top=limit)
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
                    "This is the folder to look inside, as the `uri` value that an earlier "
                    + "sharepoint_browse_folder or sharepoint_search_files result reported: "
                    + "sharepoint:///folders/{drive_id}/{item_id}. Omit it to browse the top of "
                    + "the signed-in user's own OneDrive. A folder's display name, a path, and a "
                    + "web address are not valid here."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_ITEMS,
                description=(
                    f"How many items to return from this level, at most {MAX_ITEMS}. This "
                    + "limit applies to this level only. If you raise it, this tool still does "
                    + "not reach items inside a nested folder."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> DriveFolderLevel:
        return await browse_folder(client, folder=folder, limit=limit)
