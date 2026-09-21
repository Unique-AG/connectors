from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from mcp.types import InputRequiredResult
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.models.onenote_patch_action_type import OnenotePatchActionType
from msgraph.generated.models.onenote_patch_content_command import OnenotePatchContentCommand
from msgraph.generated.users.item.onenote.pages.item.onenote_page_item_request_builder import (
    OnenotePageItemRequestBuilder,
)
from msgraph.generated.users.item.onenote.pages.item.onenote_patch_content import (
    onenote_patch_content_post_request_body as _post_request_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, not_graph
from office_365_mcp.shared.handles import OnenotePageHandle, onenote_page_handle
from office_365_mcp.shared.notes import (
    PAGE_EXPANSIONS,
    PAGE_FIELDS,
    UNKNOWN_AUDIENCE,
    NotebookAudience,
    PageSummary,
    notebook_audience,
    write_state_for,
)
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "onenote_rename_page"

STEP_PAGE = "page"
STEP_RENAME_PAGE = "rename_page"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "page": "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF",
    "title": "Synthetic title",
}

MAX_TITLE_CHARACTERS = 255

_PageQuery = OnenotePageItemRequestBuilder.OnenotePageItemRequestBuilderGetQueryParameters

_AUDIENCE_PAGE_FIELDS: tuple[str, ...] = ("id", "title")
_AUDIENCE_PAGE_EXPANSIONS: tuple[str, ...] = ("parentNotebook",)

_RENAME = "rename"
_DO_NOT_RENAME = "do not rename"
_NOTHING_RENAMED = "The page was not renamed."

_UNTITLED_PAGE = "an untitled page"
_UNNAMED_NOTEBOOK = "an unnamed notebook"

_DESCRIPTION = """\
Rename an existing OneNote page: change its title and nothing else on the page. Pass the `page` \
handle from a onenote_list_pages row or a onenote_create_page answer, and the new `title`. This \
tool changes nothing in the page body — for that, use onenote_edit_page instead. Renaming is \
sent as a single Microsoft Graph request that replaces the page's title element, and putting \
the same `title` again after a timeout does no harm: it sets the title to the same value rather \
than piling up a second change, which is why this call keeps Microsoft's default retry instead \
of refusing to be sent twice. This tool asks the person at the other end to confirm before \
renaming when the page's notebook is shared with other people or belongs to somebody else, or \
when Microsoft does not report who can see it, because the new title is visible to them the \
moment it is written. A page in the user's own unshared notebook is renamed without a question. \
This tool answers with the page as Microsoft's page index holds it right after the rename, and \
with `previous_title`, the title the index held just before — which can already be stale or \
empty, because that same index lags a create or an edit by minutes or far longer. The new \
`title` in the answer can likewise still show the old value for a while even though the rename \
itself has already taken effect.\
"""

_NOT_A_PAGE_HANDLE = (
    "onenote_rename_page takes a page handle. It looks like onenote:///pages/{id}, with the id "
    + "percent-encoded, for example "
    + "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF. A section handle "
    + "(onenote:///sections/{id}) is not a page handle: it names a whole section, not one page "
    + "inside it. A page title, a web address, and a bare id with no scheme are not handles "
    + "either. Take the `uri` from a onenote_list_pages row or a onenote_create_page answer, "
    + "and copy it word for word. This same value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 could not complete this rename. The handle is well formed, so the argument "
    + "is not the problem. The page was most likely deleted or moved to another section, either "
    + "of which gives it a new id that this handle does not name — or the notebook holding the "
    + "page could not be read. Either way, nothing was renamed. Find the page again with "
    + "onenote_list_pages, and take the `uri` from that new result. This same handle fails the "
    + "same way every time, so do not retry it."
)


class RenamedPage(BaseModel):
    page: PageSummary = Field(
        description=(
            "The page as Microsoft's page index holds it right after the rename. That index "
            + "lags an edit, by minutes or far longer, so its own `title` and "
            + "`last_modified_at` can still show the values from before this rename."
        )
    )
    previous_title: str | None = Field(
        description=(
            "The title Microsoft's page index held for this page just before the rename, read "
            + "from a pre-read this call made before writing anything. This can already be "
            + "stale, or empty, because that same index lags a create or an edit — on a test "
            + "tenant a page this connector created still carried an empty title three days "
            + "later. Null when Graph reported no title."
        )
    )


async def rename_page(
    client: GraphServiceClient,
    *,
    page: str,
    title: str,
    confirm: Confirm,
    answer_pending: bool = False,
) -> RenamedPage | InputRequiredResult:
    assert 1 <= len(title) <= MAX_TITLE_CHARACTERS, (
        f"title is bounded by the schema, got {len(title)}"
    )
    handle = onenote_page_handle(page)
    if handle is None:
        raise ToolError(_NOT_A_PAGE_HANDLE)

    about = write_state_for(_RENAME, handle.page_id, title)
    refreshed: OnenotePage | None = None
    previous_title: str | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_PAGE):
            for_audience = await _page_for_audience(client, handle)
        previous_title = for_audience.title
        audience = await _audience_of(client, for_audience)
        if answer_pending or audience.reaches_others:
            with not_graph():
                answer = await confirm(_question(for_audience, title, audience), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_RENAME_PAGE):
                await _rename(client, handle, title)
            with graph_step(STEP_PAGE):
                refreshed = await _page(client, handle)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert refreshed is not None, "a write neither asked about nor refused wrote nothing"
    summary = PageSummary.from_page(refreshed)
    assert summary is not None, "Graph re-read a page it gave no id, which cannot be addressed"
    return RenamedPage(page=summary, previous_title=previous_title)


async def _audience_of(client: GraphServiceClient, page: OnenotePage) -> NotebookAudience:
    parent = page.parent_notebook
    notebook_id = parent.id if parent is not None else None
    if notebook_id is None:
        return UNKNOWN_AUDIENCE
    return await notebook_audience(client, notebook_id)


def _question(page: OnenotePage, title: str, audience: NotebookAudience) -> str:
    old = page.title or _UNTITLED_PAGE
    name = audience.name or _UNNAMED_NOTEBOOK
    reason = f", {audience.reason}" if audience.reaches_others else ""
    return f"Rename the page {old!r} to {title!r} in the notebook {name!r}{reason}?"


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_RENAME, decline=_DO_NOT_RENAME, nothing_happened=_NOTHING_RENAMED
    )


async def _page_for_audience(client: GraphServiceClient, handle: OnenotePageHandle) -> OnenotePage:
    page = await client.me.onenote.pages.by_onenote_page_id(handle.page_id).get(
        request_configuration=RequestConfiguration[_PageQuery](
            query_parameters=_PageQuery(
                select=list(_AUDIENCE_PAGE_FIELDS), expand=list(_AUDIENCE_PAGE_EXPANSIONS)
            )
        )
    )
    assert page is not None, "Graph answered a page read with no page"
    return page


async def _rename(client: GraphServiceClient, handle: OnenotePageHandle, title: str) -> None:
    command = OnenotePatchContentCommand(
        target="title", action=OnenotePatchActionType.Replace, content=title
    )
    body = _post_request_body.OnenotePatchContentPostRequestBody(commands=[command])
    await client.me.onenote.pages.by_onenote_page_id(handle.page_id).onenote_patch_content.post(
        body
    )


async def _page(client: GraphServiceClient, handle: OnenotePageHandle) -> OnenotePage:
    page = await client.me.onenote.pages.by_onenote_page_id(handle.page_id).get(
        request_configuration=RequestConfiguration[_PageQuery](
            query_parameters=_PageQuery(select=list(PAGE_FIELDS), expand=list(PAGE_EXPANSIONS))
        )
    )
    assert page is not None, "Graph answered a page re-read with no page"
    return page


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Rename a Page",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def onenote_rename_page(
        page: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the page to rename, from a onenote_list_pages row or a "
                    + "onenote_create_page answer: `uri`, copied word for word. The shape is "
                    + "onenote:///pages/{id}. A section handle, onenote:///sections/{id}, is "
                    + "not a page handle. Never build one yourself: a page id alone, without "
                    + "this connector's scheme around it, reaches nothing."
                ),
            ),
        ],
        title: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_TITLE_CHARACTERS,
                description=(
                    "The page's new title, as the user wrote it. This tool answers with what "
                    + "Microsoft actually stored, read back off its response rather than echoed "
                    + "from this argument, so read that back rather than assuming it equals "
                    + "this value."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> RenamedPage | InputRequiredResult:
        return await rename_page(
            client,
            page=page,
            title=title,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
