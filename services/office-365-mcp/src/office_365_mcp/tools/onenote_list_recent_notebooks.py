from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.onenote_source_service import OnenoteSourceService
from msgraph.generated.models.recent_notebook import RecentNotebook as GraphRecentNotebook
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors
from office_365_mcp.shared.notes import client_url_of, web_url_of
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

_SourceService = Literal["Unknown", "OneDrive", "OneDriveForBusiness", "OnPremOneDriveForBusiness"]

_SOURCE_SERVICE_TEXT: Mapping[OnenoteSourceService, _SourceService] = {
    OnenoteSourceService.Unknown: "Unknown",
    OnenoteSourceService.OneDrive: "OneDrive",
    OnenoteSourceService.OneDriveForBusiness: "OneDriveForBusiness",
    OnenoteSourceService.OnPremOneDriveForBusiness: "OnPremOneDriveForBusiness",
}

TOOL_NAME = "onenote_list_recent_notebooks"

STEP_RECENT_NOTEBOOKS = "recent_notebooks"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

MAX_RECENT = 50

_DESCRIPTION = """\
Lists the notebooks the signed-in user recently opened, as Microsoft recorded it, newest \
access first. This is Microsoft's own memory of recent activity, not a full listing. \
onenote_list_notebooks is the sibling for the full list. A row here carries no handle. Pass \
its `web_url` to onenote_find_notebook_from_url to get one.\
"""


class RecentNotebook(BaseModel):
    name: str | None = Field(
        description=(
            "The notebook's display name, as Microsoft's recent-activity list holds it. Null "
            + "when Graph did not report one."
        )
    )
    last_accessed_at: datetime | None = Field(
        description=(
            "When the signed-in user last opened this notebook, as Graph reported it. Null "
            + "when Graph recorded none. This tracks when the user opens the notebook in a "
            + "OneNote client. It can lag behind a read or a write made through Graph."
        )
    )
    web_url: str | None = Field(
        description="The address that opens this notebook in OneNote on the web."
    )
    client_url: str | None = Field(
        description=(
            "The address that opens this notebook in the OneNote desktop app, if the person has "
            + "it installed."
        )
    )
    source_service: _SourceService | None = Field(
        description=(
            "The backend store that holds this notebook, not who owns it. Microsoft's own "
            + 'documentation names "OneDriveForBusiness" and "OneDrive". The underlying '
            + 'service can also report "OnPremOneDriveForBusiness" or "Unknown". Informational '
            + "only. Null when Graph did not report it."
        )
    )


class RecentNotebooks(BaseModel):
    notebooks: list[RecentNotebook] = Field(
        description=(
            "The notebooks in this answer, newest access first. `capped` true can leave this "
            + "list short. Empty when Microsoft has no recent-activity record for this user."
        )
    )
    capped: bool = Field(
        description=(
            f"True when a safety cap of {MAX_RECENT} stopped this list while Microsoft still "
            + "had more to give. This tool has no `limit` to raise: list the user's notebooks "
            + "with onenote_list_notebooks instead when the fifty most recently opened are not "
            + "enough. False means the list is complete."
        )
    )


async def list_recent_notebooks(
    client: GraphServiceClient, *, include_personal_notebooks: bool = True
) -> RecentNotebooks:
    with graph_errors(TOOL_NAME, step=STEP_RECENT_NOTEBOOKS):
        first_page = await (
            client.me.onenote.notebooks.get_recent_notebooks_with_include_personal_notebooks(
                include_personal_notebooks
            ).get()
        )
        assert first_page is not None, "Graph answered getRecentNotebooks with no collection"
        collected = await collect_pages(
            first_page, client, limit=MAX_RECENT, max_scanned=MAX_RECENT
        )

    return RecentNotebooks(
        notebooks=[_row(item) for item in collected.items], capped=collected.capped
    )


def _row(item: GraphRecentNotebook) -> RecentNotebook:
    return RecentNotebook(
        name=item.display_name,
        last_accessed_at=item.last_accessed_time,
        web_url=web_url_of(item.links),
        client_url=client_url_of(item.links),
        source_service=(
            None if item.source_service is None else _SOURCE_SERVICE_TEXT[item.source_service]
        ),
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Recent Notebooks",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def onenote_list_recent_notebooks(
        include_personal_notebooks: Annotated[
            bool,
            Field(
                description=(
                    "Whether to include the notebooks the signed-in user owns. True, the "
                    + "default, includes both the user's own notebooks and the ones other "
                    + "people gave them access to. False leaves out the user's own notebooks. "
                    + "On a work tenant the list can then be empty, because the user's own "
                    + 'notebooks count as "personal" even there.'
                ),
            ),
        ] = True,
        client: GraphServiceClient = graph,
    ) -> RecentNotebooks:
        return await list_recent_notebooks(
            client, include_personal_notebooks=include_personal_notebooks
        )
