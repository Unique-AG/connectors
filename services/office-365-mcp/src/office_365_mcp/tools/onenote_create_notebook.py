from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, cast

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.notebook import Notebook
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, no_retry, not_graph
from office_365_mcp.shared.handles import OnenoteNotebookHandle, OnenoteOwner
from office_365_mcp.shared.notes import (
    client_url_of,
    onenote_root,
    owner_named,
    web_url_of,
    write_state_for,
)
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "onenote_create_notebook"

STEP_CREATE_NOTEBOOK = "create_notebook"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("onenote_list_notebooks",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"name": "Synthetic notebook"}

MAX_NAME_CHARACTERS = 128

_CREATE = "create"
_DO_NOT_CREATE = "do not create"
_NOTHING_CREATED = "No notebook was created."

_DESCRIPTION = """\
Creates a new, empty notebook in the signed-in user's own OneNote, or in a Microsoft 365 group or \
team with `group`. There is no draft and no review step. Without `group`, a new notebook belongs \
to the user alone and starts unshared, so this tool never asks anybody to agree.

Notes:
- This tool asks the user to agree before it creates a notebook in a group. Every member of the \
group can open that notebook.
- Microsoft refuses a duplicate name, and the same name fails again.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
onenote_list_notebooks with the same `group` does not show a notebook named `name`.
"""


class CreatedNotebook(BaseModel):
    uri: str = Field(
        description=(
            "This new notebook's handle: onenote:///notebooks/{id}, with the id percent-encoded. "
            + "A handle from a group notebook starts with onenote:///groups/{group}/ instead. "
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
            "True when this new notebook is also the signed-in user's default notebook. Without "
            + "`group`, this is possible only when the user had no notebook before this call. "
            + "Null when Graph did not report it."
        )
    )
    is_shared: bool | None = Field(
        description=(
            "Whether this notebook is shared with anybody besides the user. Without `group`, a "
            + "brand-new notebook is always unshared, so this reads false unless Graph did not "
            + "report it."
        )
    )
    user_role: str | None = Field(
        description=(
            "The signed-in user's own access to this notebook, exactly as Microsoft spells it: "
            + '"Owner", "Contributor", "Reader", or "None" for no access. Without `group`, a '
            + 'notebook this call created is always "Owner". Null when Graph did not report it.'
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


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
    )


async def create_notebook(
    client: GraphServiceClient,
    *,
    name: str,
    group: str | None = None,
    confirm: Confirm,
    answer_pending: bool = False,
) -> CreatedNotebook | InputRequiredResult:
    assert 1 <= len(name) <= MAX_NAME_CHARACTERS, f"name is bounded by the schema, got {len(name)}"
    owner = owner_named(group=group, site=None)
    about = write_state_for("create_notebook", group or "", name)

    created: Notebook | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME, step=STEP_CREATE_NOTEBOOK):
        if answer_pending or group is not None:
            with not_graph():
                answer = await confirm(_question(name, group), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            created = await onenote_root(client, owner).notebooks.post(
                Notebook(display_name=name),
                request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
            )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert created is not None, "Graph answered a notebook create with no notebook"
    return _answer(created, owner)


def _question(name: str, group: str | None) -> str:
    if group is None:
        return f"Create the notebook {name!r} in your own OneNote?"
    return (
        f"Create the notebook {name!r} in the Microsoft 365 group {group!r}, which every member "
        + "of the group can open?"
    )


def _answer(notebook: Notebook, owner: OnenoteOwner | None) -> CreatedNotebook:
    assert notebook.id is not None, (
        "Graph created a notebook it gave no id, which cannot be addressed"
    )
    return CreatedNotebook(
        uri=OnenoteNotebookHandle(notebook.id, owner=owner).uri,
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
                    "The new notebook's name, as the user writes it. The name must be unique in "
                    + "the OneNote of its owner, at most 128 characters long, and must not "
                    + "contain any of these characters: ? * / : < > | ' \". Microsoft refuses a "
                    + "bad name and creates nothing. The answer's `name` is what Microsoft "
                    + "stored. Read it from the answer, not from this argument."
                ),
            ),
        ],
        ctx: Context,
        group: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The Microsoft 365 group or team that owns the new notebook, as its Graph "
                    + "id. A team id is a group id. Take it from teams_list_my_teams, or ask the "
                    + "user for it. Omit it to create the notebook in the user's own OneNote."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> CreatedNotebook | InputRequiredResult:
        return await create_notebook(
            client,
            name=name,
            group=group,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
