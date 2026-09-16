"""`sharepoint_read_file`: one file's own bytes, from a handle another tool made."""

from collections.abc import Mapping
from typing import Annotated, override

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import File
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.drives.item.items.item.drive_item_item_request_builder import (
    DriveItemItemRequestBuilder,
)
from msgraph.generated.models.drive_item import DriveItem
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.files import ITEM_FIELDS
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle, drive_file_handle
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "sharepoint_read_file"

STEP_ITEM = "drive_item"
STEP_CONTENT = "drive_content"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "file": "sharepoint:///files/b%21SYNTHETICDRIVE0000/01SYNTHETICFILE0000"
}

MAX_BYTES = 10 * 1024 * 1024

_MEGABYTE = 1024 * 1024

_DEFAULT_MEDIA_TYPE = "application/octet-stream"

_DESCRIPTION = f"""\
Read one file from OneDrive or SharePoint and return the file itself. Pass the `file` handle from \
a sharepoint_search_files hit or a sharepoint_browse_folder row. The file comes back in its \
original format, exactly as Microsoft stores it. This tool converts nothing and it reads nothing \
out of the file. It does not turn a document into text. A Word file comes back as a Word file. A \
PowerPoint file comes back as a PowerPoint file. Open the file yourself after this tool returns \
it, or give it to the user. A folder has no content: browse a folder with \
sharepoint_browse_folder. A file above {MAX_BYTES // _MEGABYTE} MB is refused, because the whole \
file travels in one message.\
"""

_NOT_A_FILE_HANDLE = (
    "sharepoint_read_file did not get a file handle. A file handle looks like "
    + "sharepoint:///files/{drive_id}/{item_id}, with both ids percent-encoded, for example "
    + "sharepoint:///files/b%21SYNTHETICDRIVE0000/01SYNTHETICFILE0000. A folder handle looks like "
    + "sharepoint:///folders/{drive_id}/{item_id} and is not a file handle. A folder holds no "
    + "content: pass a folder handle to sharepoint_browse_folder instead. A web address is not a "
    + "handle either. A link that opens the file in a browser reaches nothing here, and no site "
    + "name, folder name or file name becomes a handle. Take the `uri` of a "
    + "sharepoint_search_files hit or of a sharepoint_browse_folder row, and copy it word for "
    + "word. This same value fails again, so do not retry it."
)

_NOTHING_CAME_BACK = (
    "Microsoft 365 sent no content for this file, and it also reports that the file holds data. "
    + "So there is nothing to give you. This is a fault on Microsoft's side. It is not a bad "
    + "argument, and a different handle will not help. Ask for this file again later. If it fails "
    + "again, tell the user to open the file in a browser."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this file. The handle is well formed, so the argument is not "
    + "the problem. The file was most probably deleted, or somebody moved it to another drive. A "
    + "handle names the drive as well as the file, so a file that moved to another drive needs a "
    + "new handle. Search again with sharepoint_search_files, or browse the folder again with "
    + "sharepoint_browse_folder, and take the `uri` from that new result. The same handle fails "
    + "the same way, so do not retry it."
)

_ItemQuery = DriveItemItemRequestBuilder.DriveItemItemRequestBuilderGetQueryParameters


class _FileFromGraph(File):
    """A file that carries the media type Microsoft Graph reported for it."""

    def __init__(self, content: bytes, *, name: str | None, mime_type: str) -> None:
        self.mime_type: str = mime_type
        super().__init__(data=content, name=name)

    @override
    def _get_mime_type(self) -> str:
        return self.mime_type


async def sharepoint_read_file(client: GraphServiceClient, *, file: str) -> File:
    """The bytes of the file `file` addresses, under its own name and media type."""
    handle = drive_file_handle(file)
    if handle is None:
        raise ToolError(_NOT_A_FILE_HANDLE)

    item = await _item(client, handle)
    assert item is not None, "Graph answered a drive item read with no item"
    if item.folder is not None:
        raise ToolError(_is_a_folder(handle))
    size = item.size or 0
    if size > MAX_BYTES:
        raise ToolError(_too_large(size=size, web_url=item.web_url))

    content = await _content(client, handle)
    if content is None and size > 0:
        raise ToolError(_NOTHING_CAME_BACK)
    return _FileFromGraph(content or b"", name=item.name, mime_type=_media_type(item))


async def _item(client: GraphServiceClient, handle: DriveFileHandle) -> DriveItem | None:
    with graph_errors(TOOL_NAME, step=STEP_ITEM):
        return await (
            client.drives.by_drive_id(handle.drive_id)
            .items.by_drive_item_id(handle.item_id)
            .get(
                request_configuration=RequestConfiguration[_ItemQuery](
                    query_parameters=_ItemQuery(select=list(ITEM_FIELDS))
                )
            )
        )


async def _content(client: GraphServiceClient, handle: DriveFileHandle) -> bytes | None:
    with graph_errors(TOOL_NAME, step=STEP_CONTENT):
        return await (
            client.drives.by_drive_id(handle.drive_id)
            .items.by_drive_item_id(handle.item_id)
            .content.get()
        )


def _media_type(item: DriveItem) -> str:
    reported = item.file.mime_type if item.file is not None else None
    return reported or _DEFAULT_MEDIA_TYPE


def _is_a_folder(handle: DriveFileHandle) -> str:
    return (
        "This handle names a folder, and a folder is not a file. A folder holds other items and "
        + "has no content to read. Browse it with sharepoint_browse_folder, and give that tool "
        + "this handle: "
        + DriveFolderHandle(handle.drive_id, handle.item_id).uri
        + ". Then read one of the files inside the folder."
    )


def _too_large(*, size: int, web_url: str | None) -> str:
    where = (
        "Tell the user to open the file in a browser instead, at " + web_url + "."
        if web_url is not None
        else "Microsoft gave no web address for this file, so open it from the site itself."
    )
    return (
        f"This file is {_megabytes(size)} MB, and sharepoint_read_file returns a file of "
        + f"{_megabytes(MAX_BYTES)} MB or less. The whole file must be held in memory and sent to "
        + "you in one message, so a file this large cannot come back at all. This tool never "
        + "sends part of a file: half a spreadsheet is worse than a clear refusal. "
        + where
        + " No other tool here returns this file, and a second call fails the same way."
    )


def _megabytes(size: int) -> str:
    return f"{size / _MEGABYTE:.1f}"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Read File",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def read_drive_file(
        file: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the file to read. Take the `uri` of a sharepoint_search_files "
                    + "hit or of a sharepoint_browse_folder row, and copy it word for word. The "
                    + "shape is sharepoint:///files/{drive_id}/{item_id}. A folder handle, which "
                    + "looks like sharepoint:///folders/{drive_id}/{item_id}, is not a file "
                    + "handle. A web address from a browser is not a handle. Never build a handle "
                    + "yourself: the drive id is part of it, and a file id alone reaches nothing."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> File:
        return await sharepoint_read_file(client, file=file)
