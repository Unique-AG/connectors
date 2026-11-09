from collections.abc import Mapping
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.drive import Drive
from msgraph.generated.models.drive_collection_response import DriveCollectionResponse
from msgraph.generated.sites.item.drives.drives_request_builder import (
    DrivesRequestBuilder as SiteDrivesRequestBuilder,
)
from msgraph.generated.users.item.drives.drives_request_builder import DrivesRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    MAX_SCANNED_ITEMS,
    collect_pages,
    graph_errors,
    graph_step,
)
from office_365_mcp.shared.files import DRIVE_ROOT_ITEM_ID, display_name
from office_365_mcp.shared.handles import DriveFolderHandle
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.sites import site_by_path, site_path_of

TOOL_NAME = "sharepoint_list_drives"

STEP = "my_drives"

STEP_SITE_DRIVES = "site_drives"

STEP_SITE = "site_by_url"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"site": "https://contoso.sharepoint.com/sites/Finance"}


_DRIVE_FIELDS: tuple[str, ...] = ("id", "name", "driveType", "webUrl", "description", "owner")

_DrivesQuery = DrivesRequestBuilder.DrivesRequestBuilderGetQueryParameters

_SiteDrivesQuery = SiteDrivesRequestBuilder.DrivesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists drives, each with a handle for its top folder. Without `site`, it lists the drives of the \
signed-in user. Most users have one drive, their own OneDrive. With `site`, it lists the \
document libraries of that SharePoint site. Pass `root_uri` as `folder` to \
sharepoint_browse_folder to see what a drive holds.

Notes:
- Get `site` from the `web_url` of a row of sharepoint_search_sites. A library is a drive whose \
`drive_type` is `documentLibrary`.
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
            "The address that opens this drive in a browser. Always give it to the user when you "
            + "answer about this drive. It is not a folder handle, so do not pass it to "
            + "sharepoint_browse_folder. Null when Graph reported none."
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
            root_uri=DriveFolderHandle(drive.id, DRIVE_ROOT_ITEM_ID).uri,
            name=drive.name,
            drive_type=drive.drive_type,
            web_url=drive.web_url,
            owner_name=display_name(drive.owner),
            description=drive.description,
        )


class DriveList(BaseModel):
    drives: list[DriveSummary] = Field(
        description=(
            "The drives that this call listed, in the order Microsoft returned them. Without "
            + "`site`, these are the drives of the signed-in user, and most users have one. An "
            + "empty list means that Graph reported no drive. This tool does not list "
            + "a drive that Graph reports with no id, because this tool cannot address that drive."
        )
    )
    capped: bool = Field(
        description=(
            "When a safety cap stops the listing before the last drive, this value is true. "
            + "Then `drives` can be short. When the listing ends on its own, this value is false."
        )
    )


async def list_drives(client: GraphServiceClient, *, site: str | None = None) -> DriveList:
    site_path = None if site is None else site_path_of(site, TOOL_NAME)

    with graph_errors(TOOL_NAME):
        if site_path is None:
            with graph_step(STEP):
                first_page = await client.me.drives.get(
                    request_configuration=RequestConfiguration[_DrivesQuery](
                        query_parameters=_DrivesQuery(select=list(_DRIVE_FIELDS))
                    )
                )
        else:
            first_page = await _site_drives(client, site_path)
        assert first_page is not None, "Graph answered a drive listing with no collection"
        collected = await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)

    return DriveList(
        drives=[
            row for drive in collected.items if (row := DriveSummary.from_drive(drive)) is not None
        ],
        capped=collected.capped,
    )


async def _site_drives(
    client: GraphServiceClient, site_path: str
) -> DriveCollectionResponse | None:
    with graph_step(STEP_SITE):
        found = await site_by_path(client, site_path)
    assert found is not None and found.id is not None, "Graph answered a site lookup with no site"
    with graph_step(STEP_SITE_DRIVES):
        return await client.sites.by_site_id(found.id).drives.get(
            request_configuration=RequestConfiguration[_SiteDrivesQuery](
                query_parameters=_SiteDrivesQuery(select=list(_DRIVE_FIELDS))
            )
        )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Drives",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def sharepoint_list_drives(
        site: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The web address of a SharePoint site, for example "
                    + "`https://contoso.sharepoint.com/sites/Finance`. Copy it from the "
                    + "`web_url` of a row of sharepoint_search_sites. When you set it, this tool "
                    + "lists the document libraries of that site. When it is null, this tool "
                    + "lists the drives of the signed-in user."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> DriveList:
        return await list_drives(client, site=site)
