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
Create a brand-new, empty section group directly inside a notebook or another section group. \
Pass a notebook's `uri` or a section group's `uri` in `parent`; the new section group is \
created directly under whichever one you pass, never nested any deeper. A section group can \
hold both sections and further section groups, at any depth: pass any section group's own \
`uri` straight back as `parent` to nest another one under it. This is not a draft: there is no \
review step, nobody approves it first, and the section group exists the moment this tool \
returns. This connector sends no notification when it creates the section group, and Microsoft \
Graph sends none for it either, but OneNote itself can show it to people who open the notebook. \
This tool asks the person at the other end to confirm before creating the section group when \
the notebook holding `parent` is shared with other people or belongs to somebody else, or when \
Microsoft does not report who can see it, because the section group is visible to them the \
moment it is written. A section group created inside the user's own unshared notebook is \
created without a question. Section group names must be unique within the same parent, at most \
50 characters, and cannot contain any of these characters: ? * / : < > | & # ' % ~. Microsoft \
refuses a request that breaks either rule and creates nothing. If this call times out, do not \
simply call it again: Microsoft may already have created the section group before the response \
was lost, and calling again with the same `name` either creates a second section group with a \
Microsoft-adjusted name or fails as a duplicate, depending on how Microsoft resolves the clash. \
List the parent's contents with onenote_list_sections first and look for a section group \
already named `name` before calling this again. Microsoft can refuse this write with a 403 that \
looks exactly like a missing permission when `parent` names a section group — even one this \
same account just created and can create sections in elsewhere — as observed on a test tenant; \
if that happens, create directly under the notebook instead, or copy an existing section into \
that group with onenote_copy_section, which Microsoft did accept. The answer's `uri` is this \
new section group's handle: pass it to onenote_create_section to add a section to it, or to \
onenote_list_sections to see what is directly under it.\
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
            + "onenote_list_sections to see what is directly under it. It can hold further "
            + "section groups too: pass this same `uri` back as `parent` to nest one under it."
        )
    )
    name: str | None = Field(
        description=(
            "The name Microsoft actually stored for this section group, read off its response "
            + "rather than echoed from the `name` argument."
        )
    )
    created_at: datetime | None = Field(
        description=(
            "When Microsoft recorded creating this section group. Null when Graph reported none."
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
                    "Where the new section group is created, directly and one level only, as a "
                    + "`uri`: onenote:///notebooks/{id} from an onenote_list_notebooks row, a "
                    + "onenote_find_notebook_from_url answer, or a onenote_create_notebook "
                    + "answer; or onenote:///sectiongroups/{id} from an onenote_list_sections "
                    + "row, or this same tool's own answer, at any nesting depth. A section "
                    + "group can refuse this write with a 403 that looks exactly like a missing "
                    + "permission, as observed on a test tenant for a group created moments "
                    + "earlier; create directly under the notebook instead if that happens."
                ),
            ),
        ],
        name: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_NAME_CHARACTERS,
                description=(
                    "The new section group's name, as the user wrote it, up to 50 characters. "
                    + "It must be unique among the sections and section groups directly inside "
                    + "`parent`, and cannot contain any of these characters: ? * / : < > | & # "
                    + "' % ~. The answer's `name` is what Microsoft actually stored, so read "
                    + "that back rather than assuming it equals this argument."
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
