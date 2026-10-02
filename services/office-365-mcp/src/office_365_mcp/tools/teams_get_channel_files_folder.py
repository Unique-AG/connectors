from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.files import DriveItemSummary
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_get_channel_files_folder"

STEP = "channel_files_folder"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "channel_id": "19:general@thread.tacv2",
}

_DESCRIPTION = """\
Finds the SharePoint folder that holds the files of one Teams channel that the signed-in user can \
see. The answer is the folder itself and not its contents. To list what the folder holds, pass the \
`uri` of the answer as `folder` to sharepoint_browse_folder.

Notes:
- For a private channel that Microsoft migrated, the answer is the root folder.
- Microsoft documents that some special characters in a channel name make this call return an \
error.\
"""

_NO_DRIVE = (
    "Microsoft 365 answered without the drive id of the files folder of this channel. This "
    + "connector cannot browse a folder without that id. The arguments are not the problem. Tell "
    + "the user to open the Files tab of the channel in Teams."
)


async def teams_get_channel_files_folder(
    client: GraphServiceClient, *, team_id: str, channel_id: str
) -> DriveItemSummary:
    with graph_errors(TOOL_NAME, step=STEP):
        item = await (
            client.teams.by_team_id(team_id).channels.by_channel_id(channel_id).files_folder.get()
        )

    assert item is not None, "Graph answered a channel files folder read with no item"
    folder = DriveItemSummary.from_item(item)
    if folder is None:
        raise ToolError(_NO_DRIVE)
    return folder


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Get a Channel's Files Folder",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def get_a_channels_files_folder(
        team_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The team that owns the channel, exactly as teams_list_my_teams reported it. "
                    + "This id is opaque. Copy it. Never build one from a name. A team name is "
                    + "not an id."
                ),
            ),
        ],
        channel_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The channel to look up, exactly as teams_list_channels reported it. This id "
                    + "is opaque. Copy it. Never build one from a name. Pass it with the "
                    + "`team_id` of the same team."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> DriveItemSummary:
        return await teams_get_channel_files_folder(client, team_id=team_id, channel_id=channel_id)
