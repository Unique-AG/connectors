from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, cast

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.copy_notebook_model import CopyNotebookModel
from msgraph.generated.users.item.onenote.notebooks.get_notebook_from_web_url import (
    get_notebook_from_web_url_post_request_body as _post_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.handles import OnenoteNotebookHandle
from office_365_mcp.shared.notes import client_url_of, web_url_of
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "onenote_find_notebook_from_url"

STEP_NOTEBOOK_FROM_URL = "notebook_from_url"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read",)

MAX_WEB_URL_CHARACTERS = 2048

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "web_url": "https://onenote.example.invalid/notebooks/synthetic-notebook"
}

_DESCRIPTION = """\
Resolve a OneNote web address into a notebook handle. Pass the exact `web_url` Microsoft gave \
you — from an onenote_list_notebooks or onenote_list_recent_notebooks result, or from a \
`web_url` this connector already read off a page, section or notebook — or an address a person \
pasted from their browser or their OneNote client. Microsoft Graph accepts both a notebook's own \
web address (`https://...`) and its `onenote:` client address, and it resolves a page's or a \
section's own address to the notebook that holds it, so there is no need to trim the address \
down to the notebook first. This tool asks Microsoft directly; it does not search or guess. The \
`uri` it returns is a notebook handle: pass it to onenote_list_sections to see what the notebook \
holds, to onenote_create_section or onenote_create_section_group to add to it, or to \
onenote_copy_section or onenote_copy_notebook as a copy destination. onenote_list_recent_notebooks \
returns no handle at all, because Microsoft gives none there — call this tool with its `web_url` \
to get one.\
"""

GRAPH_NOT_FOUND = (
    "Microsoft 365 found no notebook at this address: the address names no notebook this user "
    + "can reach. It may be misspelled, point at something Microsoft does not treat as a "
    + "notebook, or name a notebook this user has no access to. Take a fresh `web_url` from "
    + "onenote_list_notebooks or onenote_list_recent_notebooks, or from a page, section or "
    + "notebook this connector already read, and copy it exactly. This same address fails "
    + "again, so do not retry it."
)


class FoundNotebook(BaseModel):
    uri: str = Field(
        description=(
            "This notebook's handle: onenote:///notebooks/{id}, with the id percent-encoded. "
            + "Pass it to onenote_list_sections, onenote_create_section or "
            + "onenote_create_section_group to work inside this notebook, or to "
            + "onenote_copy_section or onenote_copy_notebook as a copy destination. Never build "
            + "one: a notebook id alone reaches nothing."
        )
    )
    name: str | None = Field(
        description=(
            "The notebook's display name, as Microsoft stored it. Null when Microsoft named "
            + "none."
        )
    )
    is_default: bool | None = Field(
        description=(
            "True for the signed-in user's default notebook: the one onenote_create_page writes "
            + "into when it is called with no section at all. Null when Microsoft did not say."
        )
    )
    is_shared: bool | None = Field(
        description=(
            "True when this notebook is shared, so someone besides the owner can see it. Null "
            + "when Microsoft did not say."
        )
    )
    user_role: str | None = Field(
        description=(
            "The signed-in user's own access to this notebook, exactly as Microsoft spells it: "
            + '"Owner", "Contributor", "Reader", or "None" for no access. Null when Microsoft '
            + "did not say."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens this notebook in OneNote on the web, for a person to follow."
        )
    )
    client_url: str | None = Field(
        description=(
            "The address that opens this notebook in the OneNote desktop app, if the person has "
            + "it installed."
        )
    )
    created_at: datetime | None = Field(
        description=(
            "When the notebook was created, as Graph reported it. Null when Graph recorded none."
        )
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When the notebook last changed, as Graph reported it. Null when Graph recorded none."
        )
    )


async def find_notebook_from_url(client: GraphServiceClient, *, web_url: str) -> FoundNotebook:
    assert 1 <= len(web_url) <= MAX_WEB_URL_CHARACTERS, (
        f"web_url is bounded by the schema, got {len(web_url)}"
    )
    with graph_errors(TOOL_NAME), graph_step(STEP_NOTEBOOK_FROM_URL):
        found = await client.me.onenote.notebooks.get_notebook_from_web_url.post(
            _post_body.GetNotebookFromWebUrlPostRequestBody(web_url=web_url)
        )
    assert found is not None, "Graph answered getNotebookFromWebUrl with nothing"
    return _answer(found)


def _answer(found: CopyNotebookModel) -> FoundNotebook:
    assert found.id is not None, (
        "Graph answered getNotebookFromWebUrl with a notebook that has no id"
    )
    return FoundNotebook(
        uri=OnenoteNotebookHandle(found.id).uri,
        name=found.name,
        is_default=found.is_default,
        is_shared=found.is_shared,
        user_role=(
            None if found.user_role is None else cast("str", cast("object", found.user_role.value))
        ),
        web_url=web_url_of(found.links),
        client_url=client_url_of(found.links),
        created_at=found.created_time,
        last_modified_at=found.last_modified_time,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Find Notebook From URL",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def onenote_find_notebook_from_url(
        web_url: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_WEB_URL_CHARACTERS,
                description=(
                    "A OneNote web address or `onenote:` client address, exactly as Microsoft "
                    + "gave it: the `web_url` of an onenote_list_notebooks or "
                    + "onenote_list_recent_notebooks row, the `web_url` of a page or section "
                    + "this connector already read, or an address a person pasted. A page's or "
                    + "a section's own address resolves to the notebook that holds it."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> FoundNotebook:
        return await find_notebook_from_url(client, web_url=web_url)
