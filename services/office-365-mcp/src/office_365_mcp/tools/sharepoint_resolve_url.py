import base64
from collections.abc import Mapping
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.shares.item.drive_item.drive_item_request_builder import (
    DriveItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.files import ITEM_FIELDS, DriveItemSummary
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "sharepoint_resolve_url"

STEP = "shared_item"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.ReadWrite.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "url": "https://contoso.sharepoint.invalid/:w:/s/Finance/SYNTHETICLINK0000"
}

_DESCRIPTION = """\
This tool gets the handle of the file or folder that a OneDrive or SharePoint sharing link \
opens. It reads the item as the signed-in user. Pass a file handle to sharepoint_read_file and a \
folder handle to sharepoint_browse_folder. To find a file by its name or its content, use \
sharepoint_search_files instead.

Notes:
- This tool does not accept the sharing invitation that a link carries. As a result, the \
signed-in user gets no new access to the item.
- Microsoft documents this lookup for sharing links. Another form of web address can fail.
"""

_NOT_A_WEB_ADDRESS = (
    "sharepoint_resolve_url did not get a web address. It takes a full address that starts with "
    + "https:// and names a host, exactly as the user gave it. A file name, a path, or an id is "
    + "not a web address. A sharepoint:/// value is already a handle of this connector. Pass a "
    + "file handle to sharepoint_read_file and a folder handle to sharepoint_browse_folder. If "
    + "you call this tool again with the same arguments, the call will fail the same way."
)

_NO_DRIVE = (
    "Microsoft 365 found the item that this link opens, but it did not report the drive and the "
    + "id of that item. A handle needs both, so this tool cannot give a handle for this item. "
    + "Tell the user to open the link in a browser. If you call this tool again with the same "
    + "arguments, the call will fail the same way."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 found no file or folder at this link. The link can be expired or removed. It "
    + "can also be a link that does not open for the signed-in user. If this address is not a "
    + "sharing link, find the item with sharepoint_search_files instead. Otherwise, ask the user "
    + "to open the link in a browser. If you call this tool again with the same arguments, the "
    + "call will fail the same way."
)

_ItemQuery = DriveItemRequestBuilder.DriveItemRequestBuilderGetQueryParameters


async def resolve_url(client: GraphServiceClient, *, url: str) -> DriveItemSummary:
    address = url.strip()
    if not _is_web_address(address):
        raise ToolError(_NOT_A_WEB_ADDRESS)

    with graph_errors(TOOL_NAME, step=STEP):
        item = await client.shares.by_shared_drive_item_id(_sharing_token(address)).drive_item.get(
            request_configuration=RequestConfiguration[_ItemQuery](
                query_parameters=_ItemQuery(select=list(ITEM_FIELDS))
            )
        )
    assert item is not None, "Graph answered a shared item read with no item"
    summary = DriveItemSummary.from_item(item)
    if summary is None:
        raise ToolError(_NO_DRIVE)
    return summary


def _is_web_address(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname)


def _sharing_token(url: str) -> str:
    return "u!" + base64.urlsafe_b64encode(url.encode()).decode("ascii").rstrip("=")


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Resolve a File Link",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def sharepoint_resolve_url(
        url: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The sharing link to one file or folder, exactly as the user gave it. It must "
                    + "be a full web address that starts with https:// and names a host. A "
                    + "sharepoint:/// value is already a handle and needs no lookup."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> DriveItemSummary:
        return await resolve_url(client, url=url)
