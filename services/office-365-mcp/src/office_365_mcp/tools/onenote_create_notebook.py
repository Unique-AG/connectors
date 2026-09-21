from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, cast

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from msgraph.generated.models.notebook import Notebook
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry
from office_365_mcp.shared.handles import OnenoteNotebookHandle
from office_365_mcp.shared.notes import client_url_of, web_url_of
from office_365_mcp.shared.seam import WRITE_ADDITIVE, graph_client_for_caller

TOOL_NAME = "onenote_create_notebook"

STEP_CREATE_NOTEBOOK = "create_notebook"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"name": "Synthetic notebook"}

MAX_NAME_CHARACTERS = 128

_DESCRIPTION = """\
Create a brand-new, empty OneNote notebook of the signed-in user's own, right now. This is not \
a draft: there is no review step, and the notebook exists the moment this tool returns. A new \
notebook always belongs to the user alone and starts out unshared, so this tool never asks \
anybody to confirm before creating one — unlike writing a page or a section into a notebook \
that already exists, which can be shared with other people. Notebook names must be unique across \
the user's whole OneNote, at most 128 characters, and cannot contain any of these characters: \
? * / : < > | ' ". Microsoft answers a request that breaks either rule by refusing to create \
anything: a name already in use most often comes back as a conflict, and a name that is too \
long or carries a forbidden character comes back as a bad request; either way nothing is \
created, and this tool raises the failure back rather than guessing at a fix. If this call \
times out, the notebook may already have been created before the response was lost: call \
onenote_list_notebooks and look for a notebook already named `name` before calling this again, \
because a second call with the same name most likely fails as a duplicate rather than creating \
a second notebook — but do not rely on that instead of checking. The answer's `uri` is this new \
notebook's handle: pass it to onenote_create_section to add a section to it, or to \
onenote_create_section_group to add a section group. The answer's `name` is what Microsoft \
actually stored, read back off its response rather than echoed from the `name` argument.\
"""


class CreatedNotebook(BaseModel):
    uri: str = Field(
        description=(
            "This new notebook's handle: onenote:///notebooks/{id}, with the id "
            + "percent-encoded. Pass it to onenote_create_section to add a section to this "
            + "notebook, to onenote_create_section_group to add a section group, or to "
            + "onenote_list_sections to see what is directly under it."
        )
    )
    name: str | None = Field(
        description=(
            "The name Microsoft actually stored for this notebook, read off its response rather "
            + "than echoed from the `name` argument."
        )
    )
    is_default: bool | None = Field(
        description=(
            "True when this new notebook is also the signed-in user's default notebook — only "
            + "possible when the user had no notebook at all before this call. Null when "
            + "Microsoft did not say."
        )
    )
    is_shared: bool | None = Field(
        description=(
            "Whether this notebook is shared with anybody besides the user. A brand-new "
            + "notebook is always unshared, so this reads false unless Microsoft did not say."
        )
    )
    user_role: str | None = Field(
        description=(
            "The signed-in user's own access to this notebook, exactly as Microsoft spells it: "
            + '"Owner", "Contributor", "Reader", or "None" for no access. A notebook this call '
            + 'just created is always "Owner". Null when Microsoft did not say.'
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
            "When Microsoft recorded creating this notebook. Null when Graph reported none."
        )
    )


async def create_notebook(client: GraphServiceClient, *, name: str) -> CreatedNotebook:
    assert 1 <= len(name) <= MAX_NAME_CHARACTERS, f"name is bounded by the schema, got {len(name)}"
    with graph_errors(TOOL_NAME), graph_step(STEP_CREATE_NOTEBOOK):
        created = await client.me.onenote.notebooks.post(
            Notebook(display_name=name),
            request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
        )
    assert created is not None, "Graph answered a notebook create with no notebook"
    return _answer(created)


def _answer(notebook: Notebook) -> CreatedNotebook:
    assert notebook.id is not None, (
        "Graph created a notebook it gave no id, which cannot be addressed"
    )
    return CreatedNotebook(
        uri=OnenoteNotebookHandle(notebook.id).uri,
        name=notebook.display_name,
        is_default=notebook.is_default,
        is_shared=notebook.is_shared,
        user_role=(
            None
            if notebook.user_role is None
            else cast("str", cast("object", notebook.user_role.value))
        ),
        web_url=web_url_of(notebook.links),
        client_url=client_url_of(notebook.links),
        created_at=notebook.created_date_time,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Notebook",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def onenote_create_notebook(
        name: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_NAME_CHARACTERS,
                description=(
                    "The new notebook's name, as the user wrote it, up to 128 characters. It "
                    + "must be unique across the user's whole OneNote, and cannot contain any of "
                    + "these characters: ? * / : < > | ' \". The answer's `name` is what "
                    + "Microsoft actually stored, so read that back rather than assuming it "
                    + "equals this argument."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> CreatedNotebook:
        return await create_notebook(client, name=name)
