from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from mcp.types import InputRequiredResult
from msgraph.generated.users.item.onenote.sections.item import (
    onenote_section_item_request_builder,
)
from msgraph.generated.users.item.onenote.sections.item.copy_to_notebook import (
    copy_to_notebook_post_request_body as _copy_to_notebook_body,
)
from msgraph.generated.users.item.onenote.sections.item.copy_to_section_group import (
    copy_to_section_group_post_request_body as _copy_to_section_group_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import (
    FetchedResponse,
    fetch_response,
    graph_errors,
    graph_step,
    native_response,
    no_retry,
    not_graph,
)
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
    accepted_operation,
    notebook_audience,
    section_group_container,
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

STEP_SECTION = "section"
STEP_COPY_SECTION = "copy_section"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

MAX_NEW_NAME_CHARACTERS = 50

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "section": "onenote:///sections/1-SYNTHETICSECTION0000",
    "to_notebook": "onenote:///notebooks/1-SYNTHETICNOTEBOOK0000",
}

_SectionItemBuilder = onenote_section_item_request_builder.OnenoteSectionItemRequestBuilder
_SectionQuery = _SectionItemBuilder.OnenoteSectionItemRequestBuilderGetQueryParameters

_SECTION_NAME_FIELDS: tuple[str, ...] = ("id", "displayName")

_COPY = "copy"
_DO_NOT_COPY = "do not copy"
_NOTHING_COPIED = "Nothing was copied."

_UNNAMED_SECTION = "an unnamed section"
_UNNAMED_SECTION_GROUP = "an unnamed section group"
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
    + "the copy should land, and leave the other argument out entirely. A corrected call "
    + "succeeds; the same call fails the same way."
)

_NOT_A_NOTEBOOK_HANDLE = (
    "onenote_copy_section takes a notebook handle in `to_notebook`, if given at all. It looks "
    + "like onenote:///notebooks/{id}, and it comes from the `uri` of a onenote_list_notebooks, "
    + "onenote_find_notebook_from_url or onenote_create_notebook result. A section handle or a "
    + "section group handle is not a notebook handle. Copy it word for word, or pass "
    + "`to_section_group` instead. A corrected call succeeds; the same call fails the same way."
)

_NOT_A_SECTION_GROUP_HANDLE = (
    "onenote_copy_section takes a section group handle in `to_section_group`, if given at all. "
    + "It looks like onenote:///sectiongroups/{id}, and it comes from the `uri` of a section "
    + "group in a onenote_list_sections result or a onenote_create_section_group answer. A "
    + "notebook handle or a section handle is not a section group handle. Copy it word for "
    + "word, or pass `to_notebook` instead. A corrected call succeeds; the same call fails the "
    + "same way."
)

_NO_OPERATION_NAMED = (
    "Microsoft accepted this copy but named no operation to follow: the response carried "
    + "neither an operation in its body nor an Operation-Location header. The copy may still be "
    + "running with nothing here able to track it. Poll nothing; instead look for the result "
    + "with onenote_list_sections after a while, and do not call this tool again for the same "
    + "copy — that starts a second, independent one."
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
times out, a copy may already be running on Microsoft's side, and calling this tool again with \
the same arguments starts a second, independent copy of the section, with every one of its \
pages copied twice. On a timeout, nothing came back to poll: list the destination's sections \
with onenote_list_sections and look for one with this section's name (or `new_name`, if one \
was given) before calling again — Microsoft's index can lag a copy just as it lags a create.\
"""


def _destination(
    to_notebook: str | None, to_section_group: str | None
) -> OnenoteNotebookHandle | OnenoteSectionGroupHandle:
    if to_notebook is not None and to_section_group is not None:
        raise ToolError(_NEED_EXACTLY_ONE_DESTINATION)
    if to_notebook is not None:
        notebook_handle = onenote_notebook_handle(to_notebook)
        if notebook_handle is None:
            raise ToolError(_NOT_A_NOTEBOOK_HANDLE)
        return notebook_handle
    if to_section_group is not None:
        group_handle = onenote_section_group_handle(to_section_group)
        if group_handle is None:
            raise ToolError(_NOT_A_SECTION_GROUP_HANDLE)
        return group_handle
    raise ToolError(_NEED_EXACTLY_ONE_DESTINATION)


async def _destination_container(
    client: GraphServiceClient, destination: OnenoteNotebookHandle | OnenoteSectionGroupHandle
) -> tuple[str | None, NotebookAudience]:
    if isinstance(destination, OnenoteNotebookHandle):
        audience = await notebook_audience(client, destination.notebook_id)
        return audience.name, audience
    container = await section_group_container(client, destination.section_group_id)
    return container.name, container.notebook


async def _section_name(client: GraphServiceClient, section_id: str) -> str | None:
    found = await client.me.onenote.sections.by_onenote_section_id(section_id).get(
        request_configuration=RequestConfiguration[_SectionQuery](
            query_parameters=_SectionQuery(select=list(_SECTION_NAME_FIELDS))
        )
    )
    assert found is not None, "Graph answered a section read with no section"
    return found.display_name


def _question(
    destination: OnenoteNotebookHandle | OnenoteSectionGroupHandle,
    destination_name: str | None,
    audience: NotebookAudience,
    section_name: str | None,
    new_name: str | None,
) -> str:
    section = section_name or _UNNAMED_SECTION
    nb = audience.name or _UNNAMED_NOTEBOOK
    if isinstance(destination, OnenoteNotebookHandle):
        where = f"the notebook {nb!r}"
    else:
        group = destination_name or _UNNAMED_SECTION_GROUP
        where = f"the section group {group!r} of the notebook {nb!r}"
    renamed = f", renamed {new_name!r}" if new_name is not None else ""
    return f"Copy the section {section!r} into {where}{renamed}, {audience.reason}?"


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

    about = write_state_for("copy_section", handle.section_id, destination.uri, new_name or "")
    fetched: FetchedResponse | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        destination_name, audience = await _destination_container(client, destination)
        if answer_pending or audience.reaches_others:
            with graph_step(STEP_SECTION):
                section_name = await _section_name(client, handle.section_id)
            with not_graph():
                answer = await confirm(
                    _question(destination, destination_name, audience, section_name, new_name),
                    about,
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_COPY_SECTION):
                fetched = await _copy(client, handle.section_id, destination, new_name)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert fetched is not None, "a copy neither asked about nor refused sent nothing"
    summary = accepted_operation(fetched)
    if summary is None:
        raise ToolError(_NO_OPERATION_NAMED)
    return summary


async def _copy(
    client: GraphServiceClient,
    section_id: str,
    destination: OnenoteNotebookHandle | OnenoteSectionGroupHandle,
    new_name: str | None,
) -> FetchedResponse:
    if isinstance(destination, OnenoteNotebookHandle):
        return await _copy_to_notebook(client, section_id, destination.notebook_id, new_name)
    return await _copy_to_section_group(client, section_id, destination.section_group_id, new_name)


async def _copy_to_notebook(
    client: GraphServiceClient, section_id: str, notebook_id: str, new_name: str | None
) -> FetchedResponse:
    builder = client.me.onenote.sections.by_onenote_section_id(section_id).copy_to_notebook
    request = RequestInformation(Method.POST, builder.url_template, builder.path_parameters)
    request.headers.try_add("Accept", "application/json")
    request.set_content_from_parsable(  # pyright: ignore[reportUnknownMemberType]
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        "application/json",
        _copy_to_notebook_body.CopyToNotebookPostRequestBody(id=notebook_id, rename_as=new_name),
    )
    request.add_request_options([*no_retry(), *native_response()])
    return await fetch_response(client, request)


async def _copy_to_section_group(
    client: GraphServiceClient, section_id: str, section_group_id: str, new_name: str | None
) -> FetchedResponse:
    builder = client.me.onenote.sections.by_onenote_section_id(section_id).copy_to_section_group
    request = RequestInformation(Method.POST, builder.url_template, builder.path_parameters)
    request.headers.try_add("Accept", "application/json")
    request.set_content_from_parsable(  # pyright: ignore[reportUnknownMemberType]
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        "application/json",
        _copy_to_section_group_body.CopyToSectionGroupPostRequestBody(
            id=section_group_id, rename_as=new_name
        ),
    )
    request.add_request_options([*no_retry(), *native_response()])
    return await fetch_response(client, request)


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
                    + "onenote_find_notebook_from_url result, or a onenote_create_notebook "
                    + "answer: onenote:///notebooks/{id}. Give exactly one of `to_notebook` and "
                    + "`to_section_group`; giving both, or neither, is refused."
                ),
            ),
        ] = None,
        to_section_group: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The destination section group, as the `uri` of a section group in a "
                    + "onenote_list_sections result, or a onenote_create_section_group answer: "
                    + "onenote:///sectiongroups/{id}. Give exactly one of `to_notebook` and "
                    + "`to_section_group`; giving both, or neither, is refused. On the test "
                    + "tenant a copy into a section group succeeded even where listing or "
                    + "writing directly into that same group was refused."
                ),
            ),
        ] = None,
        new_name: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=MAX_NEW_NAME_CHARACTERS,
                description=(
                    "A new name for the copy. Omit it to keep the section's own name. Section "
                    + "names are unique within the same hierarchy level, take at most 50 "
                    + "characters, and cannot contain any of these characters: "
                    + "? * / : < > | & # ' % ~. Microsoft refuses a name that breaks either "
                    + "rule, and this tool forwards that refusal."
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
