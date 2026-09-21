from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from mcp.types import InputRequiredResult
from msgraph.generated.users.item.onenote.pages.item.copy_to_section import (
    copy_to_section_post_request_body as _copy_to_section_body,
)
from msgraph.generated.users.item.onenote.pages.item.onenote_page_item_request_builder import (
    OnenotePageItemRequestBuilder,
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
    OnenotePageHandle,
    onenote_page_handle,
    onenote_section_handle,
)
from office_365_mcp.shared.notes import (
    NotebookAudience,
    OperationSummary,
    accepted_operation,
    section_container,
    write_state_for,
)
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "onenote_copy_page"

STEP_COPY_PAGE = "copy_page"
STEP_PAGE = "page"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read", "Notes.Create")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "page": "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF",
    "to_section": "onenote:///sections/1-SYNTHETICSECTION0000",
}

_PageQuery = OnenotePageItemRequestBuilder.OnenotePageItemRequestBuilderGetQueryParameters

_AUDIENCE_PAGE_FIELDS: tuple[str, ...] = ("id", "title")

_COPY = "copy"
_DO_NOT_COPY = "do not copy"
_NOTHING_COPIED = "Nothing was copied."

_UNTITLED_PAGE = "an untitled page"
_UNNAMED_SECTION = "an unnamed section"
_UNNAMED_NOTEBOOK = "an unnamed notebook"

_NOT_A_PAGE_HANDLE = (
    "onenote_copy_page takes a page handle in `page`. It looks like onenote:///pages/{id}, with "
    + "the id percent-encoded, for example "
    + "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF. A section handle "
    + "(onenote:///sections/{id}) is not a page handle: it names a whole section, not one page "
    + "inside it. Take the `uri` from a onenote_list_pages row or a onenote_create_page answer, "
    + "and copy it word for word. This same value fails again, so do not retry it."
)

_NOT_A_SECTION_HANDLE = (
    "onenote_copy_page takes a section handle in `to_section`. It looks like "
    + "onenote:///sections/{id}, and it comes from the `uri` of a section in an "
    + "onenote_list_notebooks or onenote_list_sections result. A page handle "
    + "(onenote:///pages/{id}) and a notebook handle (onenote:///notebooks/{id}) are neither one "
    + "a section handle. Copy it word for word. This same value fails again, so do not retry it."
)

_NO_OPERATION_NAMED = (
    "Microsoft accepted this copy but named no operation to follow: the response carried "
    + "neither an operation in its body nor an Operation-Location header. The copy may still be "
    + "running with nothing here able to track it. Poll nothing; instead look for the result "
    + "with onenote_list_pages after a while, and do not call this tool again for the same copy "
    + "— that starts a second, independent one."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 could not start this copy. Both handles are well formed, so the argument is "
    + "not the problem: either the page named by `page` was deleted or moved to another section "
    + "since it was found, which gives it a new handle that this one does not name, or the "
    + "destination section named by `to_section` was deleted, moved into a different notebook, "
    + "or its notebook could not be read. Find the page again with onenote_list_pages and the "
    + "section again with onenote_list_notebooks or onenote_list_sections, and take fresh `uri` "
    + "values from those fresh results. This same pair of handles fails the same way every time, "
    + "so do not retry it unchanged."
)

_DESCRIPTION = """\
Starts a copy of one page into another section. This call does not copy the page itself: \
Microsoft runs the copy, and the answer is the operation that tracks it. Pass the answer's `uri` \
to onenote_get_operation until `status` reads Completed or Failed.

Notes:
- This tool asks the user to agree before it writes into a notebook that is shared with other \
people or belongs to somebody else. A copy into the user's own unshared notebook starts without a \
question.
- If a call times out, do not call this tool again first: a second call starts a second copy. \
Before you call again, make sure that onenote_list_pages does not show the page in the \
destination section.
"""


def _question(title: str | None, section_name: str | None, audience: NotebookAudience) -> str:
    named = title or _UNTITLED_PAGE
    section = section_name or _UNNAMED_SECTION
    name = audience.name or _UNNAMED_NOTEBOOK
    return (
        f"Copy the page {named!r} into the section {section!r} of the notebook {name!r}, "
        + f"{audience.reason}?"
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_COPY, decline=_DO_NOT_COPY, nothing_happened=_NOTHING_COPIED)


async def copy_page(
    client: GraphServiceClient,
    *,
    page: str,
    to_section: str,
    confirm: Confirm,
    answer_pending: bool = False,
) -> OperationSummary | InputRequiredResult:
    handle = onenote_page_handle(page)
    if handle is None:
        raise ToolError(_NOT_A_PAGE_HANDLE)
    section_handle = onenote_section_handle(to_section)
    if section_handle is None:
        raise ToolError(_NOT_A_SECTION_HANDLE)

    about = write_state_for("copy_page", handle.page_id, section_handle.section_id)
    fetched: FetchedResponse | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        container = await section_container(client, section_handle.section_id)
        audience = container.notebook
        if answer_pending or audience.reaches_others:
            with graph_step(STEP_PAGE):
                title = await _page_title(client, handle)
            with not_graph():
                answer = await confirm(_question(title, container.name, audience), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_COPY_PAGE):
                fetched = await _copy(client, handle.page_id, section_handle.section_id)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert fetched is not None, "a copy neither asked about nor refused sent nothing"
    summary = accepted_operation(fetched)
    if summary is None:
        raise ToolError(_NO_OPERATION_NAMED)
    return summary


async def _page_title(client: GraphServiceClient, handle: OnenotePageHandle) -> str | None:
    page = await client.me.onenote.pages.by_onenote_page_id(handle.page_id).get(
        request_configuration=RequestConfiguration[_PageQuery](
            query_parameters=_PageQuery(select=list(_AUDIENCE_PAGE_FIELDS))
        )
    )
    assert page is not None, "Graph answered a page read with no page"
    return page.title


async def _copy(client: GraphServiceClient, page_id: str, section_id: str) -> FetchedResponse:
    builder = client.me.onenote.pages.by_onenote_page_id(page_id).copy_to_section
    request = RequestInformation(Method.POST, builder.url_template, builder.path_parameters)
    request.headers.try_add("Accept", "application/json")
    request.set_content_from_parsable(  # pyright: ignore[reportUnknownMemberType]
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        "application/json",
        _copy_to_section_body.CopyToSectionPostRequestBody(id=section_id),
    )
    request.add_request_options([*no_retry(), *native_response()])
    return await fetch_response(client, request)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Copy a Page",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def onenote_copy_page(
        page: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The page to copy: the `uri` of a onenote_list_pages row or a "
                    + "onenote_create_page answer, copied word for word. The shape is "
                    + "onenote:///pages/{id}. A section handle is not a page handle."
                ),
            ),
        ],
        to_section: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The destination section, from the `uri` of a section in a "
                    + "onenote_list_notebooks or onenote_list_sections result, or a "
                    + "onenote_create_section answer. The shape is onenote:///sections/{id}. A "
                    + "page handle or a notebook handle is not a section handle. Copy it word "
                    + "for word."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> OperationSummary | InputRequiredResult:
        return await copy_page(
            client,
            page=page,
            to_section=to_section,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
