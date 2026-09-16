"""`sharepoint_browse_folder`: one level of one drive folder, and a handle for every row."""

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
Browse ONE level of a folder in OneDrive or SharePoint, and get a handle for every file and \
folder in it. Omit `folder` to see the top of the signed-in user's own OneDrive. Pass a \
folder's `uri` back as `folder` to look inside that folder. One call returns one level. It is \
not the whole folder tree, and it is not an inventory of the drive. Microsoft returns only what \
sits directly inside the folder asked about. A folder in the answer can hold more files and \
folders, and this call does not return them. To reach them, call this tool again with that \
folder's `uri`. Each row says whether it is a file or a folder, and gives its name, its size, \
when it last changed, and its handle. No file content comes back here. Use sharepoint_read_file \
to read a file. Use sharepoint_search_files to find a file by its name, or by the words inside \
it.\
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
            "The files and folders that sit directly inside the folder asked about, in the order "
            + "Microsoft returned them. This is one level, and never the whole tree. A folder in "
            + "this list can hold more items, and those items are not here. Call this tool again "
            + "with that folder's `uri` to reach them. An empty list means the folder holds "
            + "nothing. Microsoft sometimes returns an item without saying which drive holds it. "
            + "This connector cannot address such an item again, so it leaves the item out "
            + "instead of giving a handle that fails."
        )
    )
    capped: bool = Field(
        description=(
            "True when `limit` stopped the listing while Microsoft still had more of THIS level "
            + "to give. Ask again with a higher `limit` to get more of it. False when the level "
            + "ended on its own, however few items came back. It says nothing about the folders "
            + "inside this level, because this call never looks inside them."
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
    """The folder to list, or None for the root of the signed-in user's own OneDrive."""
    if folder is None:
        return None
    handle = drive_folder_handle(folder)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    return handle


async def _my_drive_root(client: GraphServiceClient) -> DriveFolderHandle:
    """The root of the signed-in user's own OneDrive, as the drive id and the root item id."""
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
                    "The folder to look inside, as the `uri` of an earlier result: "
                    + "sharepoint:///folders/{driveId}/{itemId}. Omit it to browse the top of "
                    + "the signed-in user's own OneDrive, which is where a walk starts. A folder "
                    + "name is not a handle, and neither is a path nor a web address."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_ITEMS,
                description=(
                    f"How many items to return from this one level, at most {MAX_ITEMS}. Paging "
                    + "happens inside the call, and `capped` says whether this limit stopped it. "
                    + "It bounds one level only. A higher value never reaches the items inside a "
                    + "folder in the answer."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> DriveFolderLevel:
        return await browse_folder(client, folder=folder, limit=limit)
