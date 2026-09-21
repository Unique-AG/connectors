from collections.abc import Mapping
from datetime import datetime
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from mcp.types import InputRequiredResult
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.generated.models.section_group import SectionGroup
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteSectionGroupHandle,
    onenote_container_handle,
)
from office_365_mcp.shared.notes import ContainerAudience, container_audience, write_state_for
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "onenote_create_section_group"

STEP_CREATE_SECTION_GROUP = "create_section_group"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "parent": "onenote:///notebooks/1-SYNTHETICNOTEBOOK0000",
    "name": "Synthetic section group",
}

MAX_NAME_CHARACTERS = 50

_CREATE = "create"
_DO_NOT_CREATE = "do not create"
_NOTHING_CREATED = "No section group was created."

_UNNAMED_NOTEBOOK = "an unnamed notebook"
_UNNAMED_SECTION_GROUP = "an unnamed section group"

_DESCRIPTION = """\
Creates a new, empty section group directly under `parent`, a notebook or another section group. \
OneNote can show the change to everyone who opens the notebook.

Notes:
- This tool asks the user to agree before it writes into a notebook that is shared with other \
people or belongs to somebody else. A section group in the user's own unshared notebook is \
created without a question.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
onenote_list_sections does not show a section group named `name`.
- Microsoft can refuse a create under a section group with error 403. Then create under the \
notebook, or copy a section into the group with onenote_copy_section.
"""

_NOT_A_PARENT_HANDLE = (
    "onenote_create_section_group takes a notebook handle or a section group handle in "
    + "`parent`. A notebook handle looks like onenote:///notebooks/{id} and comes from the "
    + "`uri` of a notebook in an onenote_list_notebooks result, from a "
    + "onenote_find_notebook_from_url answer, or from a onenote_create_notebook answer. A "
    + "section group handle looks like onenote:///sectiongroups/{id} and comes from the `uri` "
    + "of a section group in an onenote_list_sections result, or from this same tool's own "
    + "answer. A section handle (onenote:///sections/{id}), a page handle, a plain name and a "
    + "web address are none of them one of these. This same value fails again, so do not retry "
    + "it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not create this section group. `parent`'s handle is well formed, so the "
    + "notebook or section group it names was most likely deleted, or moved into a different "
    + "notebook, which gives it a new handle: call onenote_list_notebooks or "
    + "onenote_list_sections again and take a fresh `uri` for the parent, because this same "
    + "handle fails the same way again."
)


class CreatedSectionGroup(BaseModel):
    uri: str = Field(
        description=(
            "This new section group's handle: onenote:///sectiongroups/{id}, with the id "
            + "percent-encoded. Pass it to onenote_create_section to add a section to it, or to "
            + "onenote_list_sections to see what is directly under it."
        )
    )
    name: str | None = Field(
        description=(
            "What Microsoft stored, read from its response and not from the `name` argument."
        )
    )
    created_at: datetime | None = Field(
        description=(
            "When the section group was created, as Graph reported it. Null when Graph "
            + "recorded none."
        )
    )
    parent_uri: str = Field(
        description=(
            "The `parent` handle this section group was created directly under, spelled back."
        )
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
    )


async def create_section_group(
    client: GraphServiceClient,
    *,
    parent: str,
    name: str,
    confirm: Confirm,
    answer_pending: bool = False,
) -> CreatedSectionGroup | InputRequiredResult:
    assert 1 <= len(name) <= MAX_NAME_CHARACTERS, f"name is bounded by the schema, got {len(name)}"
    handle = onenote_container_handle(parent)
    if handle is None:
        raise ToolError(_NOT_A_PARENT_HANDLE)
    about = write_state_for("create_section_group", handle.uri, name)

    created: SectionGroup | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        container = await container_audience(client, handle)
        if answer_pending or container.notebook.reaches_others:
            with not_graph():
                answer = await confirm(_question(name, handle, container), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_CREATE_SECTION_GROUP):
                created = await _post_section_group(client, handle, name=name)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert created is not None, "Graph answered a section group create with no section group"
    return _answer(created, handle)


def _question(
    name: str,
    handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle,
    container: ContainerAudience,
) -> str:
    nb = container.notebook.name or _UNNAMED_NOTEBOOK
    if isinstance(handle, OnenoteSectionGroupHandle):
        group = container.name or _UNNAMED_SECTION_GROUP
        return (
            f"Create the section group {name!r} in the section group {group!r} of the notebook "
            + f"{nb!r}, {container.notebook.reason}?"
        )
    return f"Create the section group {name!r} in the notebook {nb!r}, {container.notebook.reason}?"


async def _post_section_group(
    client: GraphServiceClient,
    handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle,
    *,
    name: str,
) -> SectionGroup | None:
    if isinstance(handle, OnenoteNotebookHandle):
        return await client.me.onenote.notebooks.by_notebook_id(
            handle.notebook_id
        ).section_groups.post(
            SectionGroup(display_name=name),
            request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
        )
    nested = client.me.onenote.section_groups.by_section_group_id(
        handle.section_group_id
    ).section_groups
    request = RequestInformation(Method.POST, nested.url_template, dict(nested.path_parameters))
    request.headers.try_add("Accept", "application/json")
    request.set_content_from_parsable(  # pyright: ignore[reportUnknownMemberType]
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        "application/json",
        SectionGroup(display_name=name),
    )
    request.add_request_options(no_retry())
    return await client.request_adapter.send_async(  # pyright: ignore[reportUnknownMemberType]
        request, SectionGroup, {"XXX": ODataError}
    )


def _answer(
    group: SectionGroup, handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle
) -> CreatedSectionGroup:
    assert group.id is not None, (
        "Graph created a section group it gave no id, which cannot be addressed"
    )
    return CreatedSectionGroup(
        uri=OnenoteSectionGroupHandle(group.id).uri,
        name=group.display_name,
        created_at=group.created_date_time,
        parent_uri=handle.uri,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Section Group",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def onenote_create_section_group(
        parent: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Where the new section group is created, as a `uri`. A notebook's `uri` comes "
                    + "from onenote_list_notebooks, onenote_find_notebook_from_url, or "
                    + "onenote_create_notebook. A section group's `uri` comes from "
                    + "onenote_list_sections or from this same tool's own answer. A section group "
                    + "nests at any depth, so pass a group's own `uri` to nest a new section "
                    + "group under it."
                ),
            ),
        ],
        name: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_NAME_CHARACTERS,
                description=(
                    "The new section group's name, as the user writes it. The name must be "
                    + "unique among the sections and section groups directly inside the parent, "
                    + "at most 50 characters long. It must not contain any of these characters: "
                    + "? * / : < > | & # ' % ~. The answer's `name` is what Microsoft stored. "
                    + "Read it from the answer, not from this argument."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> CreatedSectionGroup | InputRequiredResult:
        return await create_section_group(
            client,
            parent=parent,
            name=name,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
