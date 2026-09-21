from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, cast

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.recent_notebook import RecentNotebook as GraphRecentNotebook
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
from office_365_mcp.shared.notes import client_url_of, web_url_of
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "onenote_list_recent_notebooks"

STEP_RECENT_NOTEBOOKS = "recent_notebooks"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

MAX_RECENT = 50

_DESCRIPTION = """\
List the notebooks Microsoft has recently seen the signed-in user open, newest access first. \
This reads a different signal than onenote_list_notebooks: it is Microsoft's own memory of \
recent activity, not a full listing, and it can include a notebook that has since been deleted \
or made unreachable. Set `include_personal_notebooks` to false to leave out the user's own \
notebooks and see only notebooks other people gave them access to; the default, true, includes \
both. A row here carries NO handle at all, because Microsoft returns none in this list — pass \
its `web_url` to onenote_find_notebook_from_url to get one before using onenote_list_sections, \
onenote_create_section, onenote_create_section_group, onenote_copy_section or \
onenote_copy_notebook. `source_service` names where Microsoft stores the notebook — OneDrive \
for the user's own notebooks, OneDriveForBusiness for a work or school one — and is \
informational only.\
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
            + "when Microsoft recorded none."
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
    source_service: str | None = Field(
        description=(
            'Where Microsoft stores this notebook, exactly as it spells it: "OneDrive" for the '
            + 'user\'s own notebook, "OneDriveForBusiness" for a work or school one. '
            + "Informational only. Null when Microsoft did not say."
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
            + "had more to give. False means the list is complete."
        )
    )


async def list_recent_notebooks(
    client: GraphServiceClient, *, include_personal_notebooks: bool = True
) -> RecentNotebooks:
    with graph_errors(TOOL_NAME), graph_step(STEP_RECENT_NOTEBOOKS):
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
            None
            if item.source_service is None
            else cast("str", cast("object", item.source_service.value))
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
                    + "shared with the user."
                ),
            ),
        ] = True,
        client: GraphServiceClient = graph,
    ) -> RecentNotebooks:
        return await list_recent_notebooks(
            client, include_personal_notebooks=include_personal_notebooks
        )
