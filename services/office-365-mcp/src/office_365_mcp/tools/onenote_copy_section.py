from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.onenote_operation import OnenoteOperation
from msgraph.generated.users.item.onenote.sections.item.copy_to_notebook import (
    copy_to_notebook_post_request_body as _copy_to_notebook_body,
)
from msgraph.generated.users.item.onenote.sections.item.copy_to_section_group import (
    copy_to_section_group_post_request_body as _copy_to_section_group_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import (
    OnenoteNotebookHandle,
    OnenoteSectionGroupHandle,
    onenote_notebook_handle,
    onenote_section_group_handle,
    onenote_section_handle,
)
from office_365_mcp.shared.notes import (
    NotebookAudience,
    OperationSummary,
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

TOOL_NAME = "onenote_copy_section"

STEP_COPY_SECTION = "copy_section"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

MAX_NEW_NAME_CHARACTERS = 50

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "section": "onenote:///sections/1-SYNTHETICSECTION0000",
    "to_notebook": "onenote:///notebooks/1-SYNTHETICNOTEBOOK0000",
}


@dataclass(frozen=True, slots=True)
class _ToNotebook:
    handle: OnenoteNotebookHandle


@dataclass(frozen=True, slots=True)
class _ToSectionGroup:
    handle: OnenoteSectionGroupHandle


type _Destination = _ToNotebook | _ToSectionGroup

_COPY = "copy"
_DO_NOT_COPY = "do not copy"
_NOTHING_COPIED = "Nothing was copied."

_UNNAMED_NOTEBOOK = "an unnamed notebook"

_NOT_A_SECTION_HANDLE = (
    "onenote_copy_section takes a section handle in `section`. It looks like "
    + "onenote:///sections/{id}, and it comes from the `uri` of a section in an "
    + "onenote_list_notebooks or onenote_list_sections result. A notebook handle "
    + "(onenote:///notebooks/{id}) and a section group handle (onenote:///sectiongroups/{id}) "
    + "are neither one a section handle. Copy it word for word. This same value fails again, so "
    + "do not retry it."
)

_NEED_EXACTLY_ONE_DESTINATION = (
    "onenote_copy_section takes exactly one destination: either `to_notebook` or "
    + "`to_section_group`, never both and never neither. Pass the one handle that names where "
    + "the copy should land, and leave the other argument out entirely."
)

_NOT_A_NOTEBOOK_HANDLE = (
    "onenote_copy_section takes a notebook handle in `to_notebook`, if given at all. It looks "
    + "like onenote:///notebooks/{id}, and it comes from the `uri` of a onenote_list_notebooks "
    + "or onenote_find_notebook_from_url result. A section handle or a section group handle is "
    + "not a notebook handle. Copy it word for word, or pass `to_section_group` instead."
)

_NOT_A_SECTION_GROUP_HANDLE = (
    "onenote_copy_section takes a section group handle in `to_section_group`, if given at all. "
    + "It looks like onenote:///sectiongroups/{id}, and it comes from the `uri` of a section "
    + "group in a onenote_list_sections result. A notebook handle or a section handle is not a "
    + "section group handle. Copy it word for word, or pass `to_notebook` instead."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 could not start this copy. Every handle given is well formed, so the "
    + "argument is not the problem: either the section named by `section` was deleted or moved "
    + "into a different notebook since it was found, which gives it a new handle that this one "
    + "does not name, or the destination named by `to_notebook` or `to_section_group` was "
    + "deleted or could not be read. Find the section again with onenote_list_sections and the "
    + "destination again with onenote_list_notebooks or onenote_list_sections, and take fresh "
    + "`uri` values from those results. This same set of handles fails the same way every time, "
    + "so do not retry it unchanged."
)

_DESCRIPTION = """\
Start copying an existing OneNote section into a different notebook or section group. Pass the \
`section` handle from a onenote_list_sections or onenote_list_notebooks result, and exactly one \
of `to_notebook` or `to_section_group` to name the destination — passing both, or passing \
neither, is refused before anything reaches Microsoft. `new_name` renames the copy; omit it and \
Microsoft names the copy the same as the section it copied. This call does NOT copy the section \
itself: Microsoft Graph runs the copy on its own side, and this tool's answer is the operation \
that tracks it, not the copied section. Pass the answer's `uri` to onenote_get_operation, a few \
seconds apart, until `status` reads Completed — its `result_uri` is then the new section's \
handle — or Failed, whose `error_code` and `error_message` say why. This tool asks the person \
at the other end to confirm before starting the copy when the destination notebook is shared \
with other people or belongs to somebody else, or when Microsoft does not report who can see \
it, because the copy becomes visible to them the moment it lands. A copy into the user's own \
unshared notebook starts without a question. This call is NOT SAFE TO RETRY BLINDLY: if it \
times out, Microsoft may already be running the copy, and calling this tool again with the same \
arguments starts a second, independent copy of the section, with every one of its pages copied \
twice. On a timeout, poll onenote_get_operation first if an operation handle came back already; \
otherwise list the destination's sections with onenote_list_sections and look for one with this \
section's name (or `new_name`, if one was given) before trying again — Microsoft's index can \
lag a copy just as it lags a create.\
"""


def _destination(to_notebook: str | None, to_section_group: str | None) -> _Destination:
    if (to_notebook is None) == (to_section_group is None):
        raise ToolError(_NEED_EXACTLY_ONE_DESTINATION)
    if to_notebook is not None:
        notebook_handle = onenote_notebook_handle(to_notebook)
        if notebook_handle is None:
            raise ToolError(_NOT_A_NOTEBOOK_HANDLE)
        return _ToNotebook(notebook_handle)
    assert to_section_group is not None, "exactly one destination is guaranteed above"
    group_handle = onenote_section_group_handle(to_section_group)
    if group_handle is None:
        raise ToolError(_NOT_A_SECTION_GROUP_HANDLE)
    return _ToSectionGroup(group_handle)


def _destination_id(destination: _Destination) -> str:
    if isinstance(destination, _ToNotebook):
        return destination.handle.notebook_id
    return destination.handle.section_group_id


async def _destination_audience(
    client: GraphServiceClient, destination: _Destination
) -> NotebookAudience:
    if isinstance(destination, _ToNotebook):
        return await notebook_audience(client, destination.handle.notebook_id)
    return await section_group_audience(client, destination.handle.section_group_id)


def _question(destination: _Destination, audience: NotebookAudience, new_name: str | None) -> str:
    name = audience.name or _UNNAMED_NOTEBOOK
    where = (
        f"the notebook {name!r}"
        if isinstance(destination, _ToNotebook)
        else f"a section group in the notebook {name!r}"
    )
    renamed = f" The copy will be named {new_name!r}." if new_name is not None else ""
    return f"Copy this section into {where}, {audience.reason}?{renamed}"


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_COPY, decline=_DO_NOT_COPY, nothing_happened=_NOTHING_COPIED)


async def copy_section(
    client: GraphServiceClient,
    *,
    section: str,
    to_notebook: str | None = None,
    to_section_group: str | None = None,
    new_name: str | None = None,
    confirm: Confirm,
    answer_pending: bool = False,
) -> OperationSummary | InputRequiredResult:
    handle = onenote_section_handle(section)
    if handle is None:
        raise ToolError(_NOT_A_SECTION_HANDLE)
    destination = _destination(to_notebook, to_section_group)

    about = write_state_for(
        "copy_section", handle.section_id, _destination_id(destination), new_name or ""
    )
    operation: OnenoteOperation | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        audience = await _destination_audience(client, destination)
        if answer_pending or audience.reaches_others:
            with not_graph():
                answer = await confirm(_question(destination, audience, new_name), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_COPY_SECTION):
                operation = await _copy(client, handle.section_id, destination, new_name)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert operation is not None, "Graph answered a section copy with no operation"
    summary = OperationSummary.from_operation(operation)
    assert summary is not None, "Graph answered a section copy with an operation that has no id"
    return summary


async def _copy(
    client: GraphServiceClient,
    section_id: str,
    destination: _Destination,
    new_name: str | None,
) -> OnenoteOperation | None:
    options = RequestConfiguration[QueryParameters](options=no_retry())
    if isinstance(destination, _ToNotebook):
        return await client.me.onenote.sections.by_onenote_section_id(
            section_id
        ).copy_to_notebook.post(
            _copy_to_notebook_body.CopyToNotebookPostRequestBody(
                id=destination.handle.notebook_id, rename_as=new_name
            ),
            request_configuration=options,
        )
    return await client.me.onenote.sections.by_onenote_section_id(
        section_id
    ).copy_to_section_group.post(
        _copy_to_section_group_body.CopyToSectionGroupPostRequestBody(
            id=destination.handle.section_group_id, rename_as=new_name
        ),
        request_configuration=options,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Copy a Section",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def onenote_copy_section(
        section: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the section to copy, from the `uri` of a section in a "
                    + "onenote_list_notebooks or onenote_list_sections result. The shape is "
                    + "onenote:///sections/{id}. Copy it word for word."
                ),
            ),
        ],
        ctx: Context,
        to_notebook: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The destination notebook, as the `uri` of a onenote_list_notebooks or "
                    + "onenote_find_notebook_from_url result: onenote:///notebooks/{id}. Give "
                    + "exactly one of `to_notebook` and `to_section_group`; giving both, or "
                    + "neither, is refused."
                ),
            ),
        ] = None,
        to_section_group: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The destination section group, as the `uri` of a section group in a "
                    + "onenote_list_sections result: onenote:///sectiongroups/{id}. Give "
                    + "exactly one of `to_notebook` and `to_section_group`; giving both, or "
                    + "neither, is refused."
                ),
            ),
        ] = None,
        new_name: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=MAX_NEW_NAME_CHARACTERS,
                description=(
                    "A new name for the copy. Omit it to keep the section's own name. Microsoft "
                    + "answers a name collision at the destination with a 400 or a 409, which "
                    + "this argument does not prevent."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> OperationSummary | InputRequiredResult:
        return await copy_section(
            client,
            section=section,
            to_notebook=to_notebook,
            to_section_group=to_section_group,
            new_name=new_name,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
