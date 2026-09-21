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

from office_365_mcp.graph_client import graph_errors, no_retry
from office_365_mcp.shared.handles import OnenoteNotebookHandle
from office_365_mcp.shared.notes import client_url_of, web_url_of
from office_365_mcp.shared.seam import WRITE_ADDITIVE, graph_client_for_caller

TOOL_NAME = "onenote_create_notebook"

STEP_CREATE_NOTEBOOK = "create_notebook"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"name": "Synthetic notebook"}

MAX_NAME_CHARACTERS = 128

_DESCRIPTION = """\
Creates a new, empty notebook for the signed-in user. There is no draft and no review step. A new \
notebook belongs to the user alone and starts unshared, so this tool never asks anybody to agree.

Notes:
- Microsoft refuses a duplicate name, and the same name fails again.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
onenote_list_notebooks does not show a notebook named `name`.
"""


class CreatedNotebook(BaseModel):
    uri: str = Field(
        description=(
            "This new notebook's handle: onenote:///notebooks/{id}, with the id percent-encoded. "
            + "Pass it to onenote_create_section to add a section, or to "
            + "onenote_create_section_group to add a section group."
        )
    )
    name: str | None = Field(
        description=(
            "What Microsoft stored, read from its response and not from the `name` argument."
        )
    )
    is_default: bool | None = Field(
        description=(
            "True when this new notebook is also the signed-in user's default notebook. This is "
            + "possible only when the user had no notebook before this call. Null when Graph did "
            + "not report it."
        )
    )
    is_shared: bool | None = Field(
        description=(
            "Whether this notebook is shared with anybody besides the user. A brand-new "
            + "notebook is always unshared, so this reads false unless Graph did not report it."
        )
    )
    user_role: str | None = Field(
        description=(
            "The signed-in user's own access to this notebook, exactly as Microsoft spells it: "
            + '"Owner", "Contributor", "Reader", or "None" for no access. A notebook this call '
            + 'created is always "Owner". Null when Graph did not report it.'
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


async def create_notebook(client: GraphServiceClient, *, name: str) -> CreatedNotebook:
    assert 1 <= len(name) <= MAX_NAME_CHARACTERS, f"name is bounded by the schema, got {len(name)}"
    with graph_errors(TOOL_NAME, step=STEP_CREATE_NOTEBOOK):
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
                    "The new notebook's name, as the user writes it. The name must be unique "
                    + "across the user's OneNote, at most 128 characters long, and must not "
                    + "contain any of these characters: ? * / : < > | ' \". Microsoft refuses a "
                    + "bad name and creates nothing. The answer's `name` is what Microsoft "
                    + "stored. Read it from the answer, not from this argument."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> CreatedNotebook:
        return await create_notebook(client, name=name)
