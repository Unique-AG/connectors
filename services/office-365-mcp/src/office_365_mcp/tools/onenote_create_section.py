from collections.abc import Mapping
from datetime import datetime
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.onenote_section import OnenoteSection
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteSectionGroupHandle,
    OnenoteSectionHandle,
    onenote_container_handle,
)
from office_365_mcp.shared.notes import (
    ContainerAudience,
    client_url_of,
    container_audience,
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

TOOL_NAME = "onenote_create_section"

STEP_CREATE_SECTION = "create_section"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "parent": "onenote:///notebooks/1-SYNTHETICNOTEBOOK0000",
    "name": "Synthetic section",
}

MAX_NAME_CHARACTERS = 50

_CREATE = "create"
_DO_NOT_CREATE = "do not create"
_NOTHING_CREATED = "No section was created."

_UNNAMED_NOTEBOOK = "an unnamed notebook"
_UNNAMED_SECTION_GROUP = "an unnamed section group"

_DESCRIPTION = """\
Create a brand-new, empty section directly inside a notebook or a section group. Pass a \
notebook's `uri` or a section group's `uri` in `parent`; the new section is created directly \
under whichever one you pass, never nested any deeper. This is not a draft: there is no review \
step, nobody approves it first, and the section exists the moment this tool returns. This \
connector sends no notification when it creates the section, and Microsoft Graph sends none for \
it either, but OneNote itself can show the new section to people who open the notebook. This \
tool asks the person at the other end to confirm before creating the section when the notebook \
holding `parent` is shared with other people or belongs to somebody else, or when Microsoft \
does not report who can see it, because the section is visible to them the moment it is \
written. A section created inside the user's own unshared notebook is created without a \
question. Section names must be unique within the same parent, at most 50 characters, and \
cannot contain any of these characters: ? * / : < > | & # ' % ~. Microsoft refuses a request \
that breaks either rule and creates nothing. If this call times out, do not simply call it \
again: Microsoft may already have created the section before the response was lost, and calling \
again with the same `name` either creates a second section with a Microsoft-adjusted name or \
fails as a duplicate, depending on how Microsoft resolves the clash. List the parent's sections \
with onenote_list_sections first and look for a section already named `name` before calling \
this again. Microsoft can refuse this write with a 403 that looks exactly like a missing \
permission when `parent` names a section group — even one this same account just created and \
can create sections in elsewhere — as observed on a test tenant; if that happens, create the \
section directly under the notebook instead, or copy an existing section into that group with \
onenote_copy_section, which Microsoft did accept. The answer's `uri` is this new section's \
handle: pass it to onenote_create_page to write the first page into it, or to onenote_list_pages \
to confirm it holds none yet.\
"""

_NOT_A_PARENT_HANDLE = (
    "onenote_create_section takes a notebook handle or a section group handle in `parent`. A "
    + "notebook handle looks like onenote:///notebooks/{id} and comes from the `uri` of a "
    + "notebook in an onenote_list_notebooks result, from a onenote_find_notebook_from_url "
    + "answer, or from a onenote_create_notebook answer. A section group handle looks like "
    + "onenote:///sectiongroups/{id} and comes from the `uri` of a section group in an "
    + "onenote_list_sections result, or from a onenote_create_section_group answer. A section "
    + "handle (onenote:///sections/{id}), a page handle, a plain name and a web address are none "
    + "of them one of these. This same value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not create this section. `parent`'s handle is well formed, so the "
    + "notebook or section group it names was most likely deleted, or moved into a different "
    + "notebook, which gives it a new handle: call onenote_list_notebooks or "
    + "onenote_list_sections again and take a fresh `uri` for the parent, because this same "
    + "handle fails the same way again."
)


class CreatedSection(BaseModel):
    uri: str = Field(
        description=(
            "This new section's handle: onenote:///sections/{id}, with the id "
            + "percent-encoded. Pass it to onenote_create_page to write the first page into it, "
            + "or to onenote_list_pages to see what it holds."
        )
    )
    name: str | None = Field(
        description=(
            "The name Microsoft actually stored for this section, read off its response rather "
            + "than echoed from the `name` argument."
        )
    )
    is_default: bool | None = Field(
        description=(
            "True when this new section is also its notebook's default section. Null when "
            + "Microsoft did not say."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens this section in OneNote on the web, for a person to follow."
        )
    )
    client_url: str | None = Field(
        description=(
            "The address that opens this section in the OneNote desktop app, if the person has "
            + "it installed."
        )
    )
    created_at: datetime | None = Field(
        description="When Microsoft recorded creating this section. Null when Graph reported none."
    )
    parent_uri: str = Field(
        description="The `parent` handle this section was created directly under, spelled back."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
    )


async def create_section(
    client: GraphServiceClient,
    *,
    parent: str,
    name: str,
    confirm: Confirm,
    answer_pending: bool = False,
) -> CreatedSection | InputRequiredResult:
    assert 1 <= len(name) <= MAX_NAME_CHARACTERS, f"name is bounded by the schema, got {len(name)}"
    handle = onenote_container_handle(parent)
    if handle is None:
        raise ToolError(_NOT_A_PARENT_HANDLE)
    about = write_state_for("create_section", handle.uri, name)

    created: OnenoteSection | None = None
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
            with graph_step(STEP_CREATE_SECTION):
                created = await _post_section(client, handle, name=name)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert created is not None, "Graph answered a section create with no section"
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
            f"Create the section {name!r} in the section group {group!r} of the notebook "
            + f"{nb!r}, {container.notebook.reason}?"
        )
    return f"Create the section {name!r} in the notebook {nb!r}, {container.notebook.reason}?"


async def _post_section(
    client: GraphServiceClient,
    handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle,
    *,
    name: str,
) -> OnenoteSection | None:
    section = OnenoteSection(display_name=name)
    request_configuration = RequestConfiguration[QueryParameters](options=no_retry())
    if isinstance(handle, OnenoteNotebookHandle):
        return await client.me.onenote.notebooks.by_notebook_id(handle.notebook_id).sections.post(
            section, request_configuration=request_configuration
        )
    return await client.me.onenote.section_groups.by_section_group_id(
        handle.section_group_id
    ).sections.post(section, request_configuration=request_configuration)


def _answer(
    section: OnenoteSection, handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle
) -> CreatedSection:
    assert section.id is not None, (
        "Graph created a section it gave no id, which cannot be addressed"
    )
    return CreatedSection(
        uri=OnenoteSectionHandle(section.id).uri,
        name=section.display_name,
        is_default=section.is_default,
        web_url=web_url_of(section.links),
        client_url=client_url_of(section.links),
        created_at=section.created_date_time,
        parent_uri=handle.uri,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Section",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def onenote_create_section(
        parent: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Where the new section is created, directly and one level only, as a `uri`: "
                    + "onenote:///notebooks/{id} from an onenote_list_notebooks row, a "
                    + "onenote_find_notebook_from_url answer, or a onenote_create_notebook "
                    + "answer; or onenote:///sectiongroups/{id} from an onenote_list_sections "
                    + "row, or a onenote_create_section_group answer. A section group can refuse "
                    + "this write with a 403 that looks exactly like a missing permission, as "
                    + "observed on a test tenant for a group created moments earlier; create "
                    + "directly under the notebook instead if that happens."
                ),
            ),
        ],
        name: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_NAME_CHARACTERS,
                description=(
                    "The new section's name, as the user wrote it, up to 50 characters. It must "
                    + "be unique among the sections and section groups directly inside `parent`, "
                    + "and cannot contain any of these characters: ? * / : < > | & # ' % ~. The "
                    + "answer's `name` is what Microsoft actually stored, so read that back "
                    + "rather than assuming it equals this argument."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> CreatedSection | InputRequiredResult:
        return await create_section(
            client,
            parent=parent,
            name=name,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
