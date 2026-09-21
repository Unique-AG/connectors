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
    onenote_notebook_handle,
    onenote_section_group_handle,
)
from office_365_mcp.shared.notes import (
    NotebookAudience,
    notebook_audience,
    section_group_audience,
    write_state_for,
)
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

_DESCRIPTION = """\
Create a brand-new, empty section group directly inside a notebook or another section group. \
Pass a notebook's `uri` or a section group's `uri` in `parent`; the new section group is \
created directly under whichever one you pass, never nested any deeper. A section group nested \
inside another section group can hold sections with onenote_create_section, but it cannot hold \
a THIRD level of section group: Microsoft Graph offers no way to create one two levels deep \
inside a section group, so pass a notebook's `uri`, or at most one section group's `uri`, in \
`parent`. This is not a draft: there is no review step, nobody approves it first, and the \
section group exists the moment this tool returns. This connector sends no notification when it \
creates the section group, and Microsoft Graph sends none for it either, but OneNote itself can \
show it to people who open the notebook. This tool asks the person at the other end to confirm \
before creating the section group when the notebook holding `parent` is shared with other \
people or belongs to somebody else, or when Microsoft does not report who can see it, because \
the section group is visible to them the moment it is written. A section group created inside \
the user's own unshared notebook is created without a question. Section group names must be \
unique within the same parent, at most 50 characters, and cannot contain any of these \
characters: ? * / : < > | & # ' % ~. Microsoft refuses a request that breaks either rule and \
creates nothing. If this call times out, do not simply call it again: Microsoft may already \
have created the section group before the response was lost, and calling again with the same \
`name` either creates a second section group with a Microsoft-adjusted name or fails as a \
duplicate, depending on how Microsoft resolves the clash. List the parent's contents with \
onenote_list_sections first and look for a section group already named `name` before calling \
this again. The answer's `uri` is this new section group's handle: pass it to \
onenote_create_section to add a section to it, or to onenote_list_sections to see what is \
directly under it.\
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
            + "onenote_list_sections to see what is directly under it. It cannot itself take "
            + "another section group two levels deep: Microsoft Graph offers no way to create "
            + "one there."
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
    handle = _parent_handle(parent)
    about = write_state_for("create_section_group", _parent_id(handle), name)

    created: SectionGroup | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        audience = await _audience_of(client, handle)
        if answer_pending or audience.reaches_others:
            with not_graph():
                answer = await confirm(_question(name, audience), about)
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


def _parent_handle(parent: str) -> OnenoteNotebookHandle | OnenoteSectionGroupHandle:
    notebook = onenote_notebook_handle(parent)
    if notebook is not None:
        return notebook
    group = onenote_section_group_handle(parent)
    if group is not None:
        return group
    raise ToolError(_NOT_A_PARENT_HANDLE)


def _parent_id(handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle) -> str:
    if isinstance(handle, OnenoteNotebookHandle):
        return handle.notebook_id
    return handle.section_group_id


async def _audience_of(
    client: GraphServiceClient, handle: OnenoteNotebookHandle | OnenoteSectionGroupHandle
) -> NotebookAudience:
    if isinstance(handle, OnenoteNotebookHandle):
        return await notebook_audience(client, handle.notebook_id)
    return await section_group_audience(client, handle.section_group_id)


def _question(name: str, audience: NotebookAudience) -> str:
    nb = audience.name or _UNNAMED_NOTEBOOK
    return f"Create the section group {name!r} in the notebook {nb!r}, {audience.reason}?"


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
    request = RequestInformation(Method.POST, nested.url_template, nested.path_parameters)
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
                    + "row, or this same tool's own answer. Passing a section group's `uri` that "
                    + "is itself already nested inside another section group fails: Microsoft "
                    + "Graph offers no way to create a section group three levels deep."
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
