from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.users.item.onenote.pages.item.copy_to_section import (
    copy_to_section_post_request_body as _copy_to_section_body,
)
from msgraph.generated.users.item.onenote.pages.item.onenote_page_item_request_builder import (
    OnenotePageItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import (
    OnenotePageHandle,
    onenote_page_handle,
    onenote_section_handle,
)
from office_365_mcp.shared.notes import (
    NotebookAudience,
    OperationSummary,
    section_audience,
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

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Create",)

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
Start copying an existing OneNote page into a different section. Pass the `page` handle from a \
onenote_list_pages row or a onenote_create_page answer, and the `to_section` handle — a \
section's `uri` from a onenote_list_notebooks or onenote_list_sections result — to name the \
destination. This call does NOT copy the page itself: Microsoft Graph runs the copy on its own \
side, and this tool's answer is the operation that tracks it, not the copied page. Pass the \
answer's `uri` to onenote_get_operation, a few seconds apart, until `status` reads Completed — \
its `result_uri` is then the new page's handle — or Failed, whose `error_code` and \
`error_message` say why. This tool asks the person at the other end to confirm before starting \
the copy when the destination section's notebook is shared with other people or belongs to \
somebody else, or when Microsoft does not report who can see it, because the copy becomes \
visible to them the moment it lands. A copy into the user's own unshared notebook starts \
without a question. This call is NOT SAFE TO RETRY BLINDLY: if it times out, Microsoft may \
already be running the copy, and calling this tool again with the same arguments starts a \
second, independent copy of the page. On a timeout, poll onenote_get_operation first if an \
operation handle came back already; otherwise list the destination section's pages with \
onenote_list_pages and look for one with this page's title before trying again — remember that \
Microsoft's page index lags a copy the same way it lags a create, so a fresh copy can still be \
missing from that listing, or show an empty title, for a while after it lands.\
"""


def _question(title: str | None, audience: NotebookAudience) -> str:
    named = title or _UNTITLED_PAGE
    name = audience.name or _UNNAMED_NOTEBOOK
    return f"Copy the page {named!r} into the section of the notebook {name!r}, {audience.reason}?"


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
    operation = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_PAGE):
            title = await _page_title(client, handle)
        audience = await section_audience(client, section_handle.section_id)
        if answer_pending or audience.reaches_others:
            with not_graph():
                answer = await confirm(_question(title, audience), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_COPY_PAGE):
                operation = await client.me.onenote.pages.by_onenote_page_id(
                    handle.page_id
                ).copy_to_section.post(
                    _copy_to_section_body.CopyToSectionPostRequestBody(
                        id=section_handle.section_id
                    ),
                    request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert operation is not None, "Graph answered a page copy with no operation"
    summary = OperationSummary.from_operation(operation)
    assert summary is not None, "Graph answered a page copy with an operation that has no id"
    return summary


async def _page_title(client: GraphServiceClient, handle: OnenotePageHandle) -> str | None:
    page = await client.me.onenote.pages.by_onenote_page_id(handle.page_id).get(
        request_configuration=RequestConfiguration[_PageQuery](
            query_parameters=_PageQuery(select=list(_AUDIENCE_PAGE_FIELDS))
        )
    )
    assert page is not None, "Graph answered a page read with no page"
    return page.title


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
                    "The handle of the page to copy, from a onenote_list_pages row or a "
                    + "onenote_create_page answer: `uri`, copied word for word. The shape is "
                    + "onenote:///pages/{id}. A section handle, onenote:///sections/{id}, is not "
                    + "a page handle. Never build one yourself: a page id alone, without this "
                    + "connector's scheme around it, reaches nothing."
                ),
            ),
        ],
        to_section: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the destination section, from the `uri` of a section in a "
                    + "onenote_list_notebooks or onenote_list_sections result. The shape is "
                    + "onenote:///sections/{id}. A page handle or a notebook handle is not a "
                    + "section handle. Copy it word for word."
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
