from collections.abc import Mapping
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import File
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.drives.item.items.item.content.content_request_builder import (
    ContentRequestBuilder,
)
from msgraph.generated.drives.item.items.item.drive_item_item_request_builder import (
    DriveItemItemRequestBuilder,
)
from msgraph.generated.models.drive_item import DriveItem
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.files import ITEM_FIELDS
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle, drive_file_handle
from office_365_mcp.shared.seam import READ_ONLY, FileFromGraph, graph_client_for_caller

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
it, or give it to the user. To read what a document says, set `convert_to` to `pdf`: Microsoft \
then converts the file on its own servers and sends a PDF, which carries the text that a Word or \
PowerPoint file hides inside a zip archive. This connector still converts nothing itself. A \
folder has no content: browse a folder with sharepoint_browse_folder. A file above \
{MAX_BYTES // _MEGABYTE} MB is refused, because the whole \
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

_NOT_A_PLAIN_FILE = (
    "Microsoft 365 does not hold this item as a plain file, so it has no single content to "
    + "return. A OneNote notebook and a shortcut to another drive both look like files and are "
    + "not: Microsoft describes them as packages, which are folders in some places and files in "
    + "others. Open this item in a browser instead. Reading it here fails the same way every "
    + "time, and no other tool here returns it."
)

_NO_SIZE = (
    "Microsoft 365 did not say how large this file is, and sharepoint_read_file will not fetch a "
    + "file whose size it does not know. The whole file must be held in memory and sent in one "
    + "message, so the size is what decides whether it can come back at all. This is a gap in "
    + "what Microsoft reported and not a bad argument. Open the file in a browser instead."
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
_ContentQuery = ContentRequestBuilder.ContentRequestBuilderGetQueryParameters

_PDF_MEDIA_TYPE = "application/pdf"

type ConvertTo = Literal["pdf"]


async def sharepoint_read_file(
    client: GraphServiceClient, *, file: str, convert_to: ConvertTo | None = None
) -> File:
    handle = drive_file_handle(file)
    if handle is None:
        raise ToolError(_NOT_A_FILE_HANDLE)

    fetched = await _fetched(client, handle, convert_to=convert_to)
    if isinstance(fetched, str):
        raise ToolError(fetched)
    return fetched


async def _fetched(
    client: GraphServiceClient, handle: DriveFileHandle, *, convert_to: ConvertTo | None
) -> File | str:
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_ITEM):
            item = await _item(client, handle)

        assert item is not None, "Graph answered a drive item read with no item"
        if item.folder is not None:
            return _is_a_folder(handle)
        if item.file is None:
            return _NOT_A_PLAIN_FILE
        if item.size is None:
            return _NO_SIZE
        if item.size > MAX_BYTES:
            return _too_large(size=item.size, web_url=item.web_url)

        with graph_step(STEP_CONTENT):
            content = await _content(client, handle, convert_to=convert_to)

        if content is None and item.size > 0:
            return _NOTHING_CAME_BACK
        body = content or b""
        if len(body) > MAX_BYTES:
            return _too_large(size=len(body), web_url=item.web_url)
        if convert_to is None:
            return FileFromGraph(body, name=item.name, mime_type=_media_type(item, body))
        return FileFromGraph(body, name=_converted_name(item.name), mime_type=_PDF_MEDIA_TYPE)


async def _item(client: GraphServiceClient, handle: DriveFileHandle) -> DriveItem | None:
    return await (
        client.drives.by_drive_id(handle.drive_id)
        .items.by_drive_item_id(handle.item_id)
        .get(
            request_configuration=RequestConfiguration[_ItemQuery](
                query_parameters=_ItemQuery(select=list(ITEM_FIELDS))
            )
        )
    )


async def _content(
    client: GraphServiceClient, handle: DriveFileHandle, *, convert_to: ConvertTo | None
) -> bytes | None:
    content = (
        client.drives.by_drive_id(handle.drive_id).items.by_drive_item_id(handle.item_id).content
    )
    if convert_to is None:
        return await content.get()
    return await content.get(
        request_configuration=RequestConfiguration[_ContentQuery](
            query_parameters=_ContentQuery(format=convert_to)
        )
    )


def _converted_name(name: str | None) -> str | None:
    if name is None:
        return None
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return f"{stem}.pdf"


def _media_type(item: DriveItem, body: bytes) -> str:
    reported = item.file.mime_type if item.file is not None else None
    if reported is None:
        return _DEFAULT_MEDIA_TYPE
    if reported.startswith("text/") and not _is_utf8(body):
        return _DEFAULT_MEDIA_TYPE
    return reported


def _is_utf8(body: bytes) -> bool:
    try:
        _ = body.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


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
        convert_to: Annotated[
            Literal["pdf"] | None,
            Field(
                description=(
                    "Ask Microsoft to convert the file to PDF before it is sent. Leave it out to "
                    + "get the file in its own format, which is the default. Microsoft does the "
                    + "conversion on its own servers; this connector never converts anything. Set "
                    + "it to `pdf` when you need to read what a document says, because a Word, "
                    + "PowerPoint or Excel file is a zip archive that you cannot read, and a PDF "
                    + "carries the text. Microsoft converts these file types: doc, docx, dot, "
                    + "dotx, eml, epub, htm, html, md, msg, odp, ods, odt, pps, ppsx, ppt, pptx, "
                    + "rtf, tif, tiff, xls, xlsm and xlsx. A file that is already a PDF is not on "
                    + "that list, so read it with no conversion. Microsoft says not every file "
                    + "can be converted, so a conversion can fail for a file that is on the list."
                )
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> File:
        return await sharepoint_read_file(client, file=file, convert_to=convert_to)
