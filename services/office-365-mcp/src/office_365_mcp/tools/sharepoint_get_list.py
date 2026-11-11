from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.handles import ListHandle, list_handle
from office_365_mcp.shared.lists import NOT_A_LIST_HANDLE, ListColumn, list_columns
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "sharepoint_get_list"

STEP = "list_columns"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Sites.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "list": ListHandle(
        "contoso.sharepoint.invalid,00000000-0000-4000-8000-00000000000a,"
        + "11111111-aaaa-bbbb-cccc-222222222222",
        "0b1c2d3e-0000-4000-8000-00000000000a",
    ).uri
}

_DESCRIPTION = """\
Describes the columns of one SharePoint list: the internal name, display name, type, and whether \
each column is required, read-only, or indexed. Choice columns carry their allowed values. Read \
this before you filter sharepoint_list_items, because a filter names a column by its internal \
name and needs an indexed column.
"""


class ListSchema(BaseModel):
    columns: list[ListColumn] = Field(
        description=(
            "Every column of the list, hidden ones included, in the order Microsoft returned "
            + "them."
        )
    )


async def get_list(client: GraphServiceClient, *, list_uri: str) -> ListSchema:
    handle = list_handle(list_uri)
    if handle is None:
        raise ToolError(f"{TOOL_NAME} {NOT_A_LIST_HANDLE}")
    with graph_errors(TOOL_NAME, step=STEP):
        columns = await list_columns(client, handle)
    return ListSchema(columns=columns)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Get List",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def sharepoint_get_list(
        list: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The list to describe: the `uri` of a row from sharepoint_list_lists. Copy "
                    + "it exactly."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> ListSchema:
        return await get_list(client, list_uri=list)
