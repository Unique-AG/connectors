from collections.abc import Mapping
from typing import Self

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.drive import Drive
from msgraph.generated.users.item.drives.drives_request_builder import DrivesRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors
from office_365_mcp.shared.files import display_name
from office_365_mcp.shared.handles import DriveFolderHandle
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "sharepoint_list_drives"

STEP = "my_drives"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

_ROOT_ITEM = "root"

_DRIVE_FIELDS: tuple[str, ...] = ("id", "name", "driveType", "webUrl", "description", "owner")

_DrivesQuery = DrivesRequestBuilder.DrivesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the drives of the signed-in user, each with a handle for its top folder. Most users have \
one drive, their own OneDrive. Pass `root_uri` as `folder` to sharepoint_browse_folder to see \
what a drive holds.

Notes:
- This tool does not list the document libraries of SharePoint sites. To find files on a site, \
use sharepoint_search_files and its `sites` answer.
"""


class DriveSummary(BaseModel):
    root_uri: str = Field(
        description=(
            "The handle of the top folder of this drive. It looks like "
            + "sharepoint:///folders/{drive_id}/root. Pass it as `folder` to "
            + "sharepoint_browse_folder to list the drive. Copy it exactly. Never build one."
        )
    )
    name: str | None = Field(
        description=(
            "The display name of the drive, for example OneDrive. Names can repeat, so use "
            + "`root_uri` to tell two drives apart. Null when Graph reported none."
        )
    )
    drive_type: str | None = Field(
        description=(
            "The kind of drive, as Graph names it. The value `personal` is a consumer OneDrive. "
            + "The value `business` is a OneDrive for work or school. The value `documentLibrary` "
            + "is a SharePoint document library. Null when Graph reported none."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens this drive in a browser. Show it to the user. It is not a "
            + "folder handle, so do not pass it to sharepoint_browse_folder. Null when Graph "
            + "reported none."
        )
    )
    owner_name: str | None = Field(
        description=(
            "The display name of the user who owns the drive. Null when the owner is not a user, "
            + "or when Graph reported no name."
        )
    )
    description: str | None = Field(
        description=(
            "The description that the owner gave the drive. An empty string means that the "
            + "drive has no description. Null when Graph reported none."
        )
    )

    @classmethod
    def from_drive(cls, drive: Drive) -> Self | None:
        if drive.id is None:
            return None
        return cls(
            root_uri=DriveFolderHandle(drive.id, _ROOT_ITEM).uri,
            name=drive.name,
            drive_type=drive.drive_type,
            web_url=drive.web_url,
            owner_name=display_name(drive.owner),
            description=drive.description,
        )


class DriveList(BaseModel):
    drives: list[DriveSummary] = Field(
        description=(
            "The drives of the signed-in user, in the order Microsoft returned them. Most users "
            + "have one. An empty list means that Graph reported no drive. This tool leaves out a "
            + "drive that Graph reports with no id, because this tool cannot address that drive."
        )
    )
    capped: bool = Field(
        description=(
            "When a safety cap stops the listing before the last drive, this value is true. "
            + "Then `drives` can be short. When the listing ends on its own, this value is false."
        )
    )


async def list_drives(client: GraphServiceClient) -> DriveList:
    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.me.drives.get(
            request_configuration=RequestConfiguration[_DrivesQuery](
                query_parameters=_DrivesQuery(select=list(_DRIVE_FIELDS))
            )
        )
        assert first_page is not None, "Graph answered a drive listing with no collection"
        collected = await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)

    return DriveList(
        drives=[
            row for drive in collected.items if (row := DriveSummary.from_drive(drive)) is not None
        ],
        capped=collected.capped,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Drives",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def sharepoint_list_drives(client: GraphServiceClient = graph) -> DriveList:
        return await list_drives(client)
