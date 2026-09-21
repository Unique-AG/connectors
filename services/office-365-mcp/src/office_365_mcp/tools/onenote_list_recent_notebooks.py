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
List the notebooks Microsoft has recently seen the signed-in user open, newest access first \
(confirmed on a test tenant). This reads a different signal than onenote_list_notebooks: it is \
Microsoft's own memory of recent activity, not a full listing. Set `include_personal_notebooks` \
to false to leave out the user's own notebooks and see only notebooks other people gave them \
access to; on \
a work tenant this can answer an empty list, because the user's own notebooks count as \
"personal" even there. A row here carries NO handle at all, because Microsoft returns none in \
this list — pass its `web_url` to onenote_find_notebook_from_url to get one before using \
onenote_list_sections, onenote_create_section, onenote_create_section_group, \
onenote_copy_section or onenote_copy_notebook. `source_service` names the backend store where \
the notebook resides, not who owns it.\
"""


class RecentNotebook(BaseModel):
    name: str | None = Field(
        description=(
            "The notebook's display name, as Microsoft's recent-activity list holds it. Null "
            + "when Microsoft named none."
        )
    )
    last_accessed_at: datetime | None = Field(
        description=(
            "When the signed-in user last opened this notebook, as Microsoft reported it. Null "
            + "when Microsoft recorded none. This tracks opening the notebook in a OneNote "
            + "client, not reading or writing it through Graph: on a test tenant this value did "
            + "not advance despite many Graph calls against the same notebook in the same "
            + "session."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens this notebook in OneNote on the web. Pass it to "
            + "onenote_find_notebook_from_url to get this notebook's handle: this row carries "
            + "none of its own."
        )
    )
    client_url: str | None = Field(
        description=(
            "The address that opens this notebook in the OneNote desktop app, if the person has "
            + "it installed."
        )
    )
    source_service: _SourceService | None = Field(
        description=(
            "The backend store where this notebook resides, as Microsoft's own documentation "
            + 'puts it: "OneDriveForBusiness" or "OneDrive". The underlying service also '
            + 'carries "OnPremOneDriveForBusiness" and "Unknown", which Microsoft\'s reference '
            + "does not explain further. On a test tenant this read OneDriveForBusiness for the "
            + "user's own notebooks on a work account, so this does not say who owns the "
            + "notebook. Informational only. Null when Microsoft did not say."
        )
    )


class RecentNotebooks(BaseModel):
    notebooks: list[RecentNotebook] = Field(
        description=(
            "The notebooks Microsoft has recently seen the signed-in user open, newest access "
            + "first, unless `capped` is true, in which case a safety cap cut the list short. "
            + "Empty when Microsoft has no recent-activity record for this user."
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
                    + "people gave them access to. Set it to false to see only the notebooks "
                    + "shared with the user: on a work tenant this can answer an empty list, "
                    + 'because the user\'s own notebooks count as "personal" even there.'
                ),
            ),
        ] = True,
        client: GraphServiceClient = graph,
    ) -> RecentNotebooks:
        return await list_recent_notebooks(
            client, include_personal_notebooks=include_personal_notebooks
        )
