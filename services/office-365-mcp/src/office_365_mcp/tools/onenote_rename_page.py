from collections.abc import Mapping
from html import escape
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.models.onenote_patch_action_type import OnenotePatchActionType
from msgraph.generated.models.onenote_patch_content_command import OnenotePatchContentCommand
from msgraph.generated.users.item.onenote.pages.item.onenote_patch_content import (
    onenote_patch_content_post_request_body as _post_request_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step, not_graph
from office_365_mcp.shared.handles import OnenotePageHandle, onenote_page_handle
from office_365_mcp.shared.notes import (
    NotebookAudience,
    PageSummary,
    page_for_a_question,
    page_summary,
    write_state_for,
)
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "onenote_rename_page"

STEP_RENAME_PAGE = "rename_page"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "page": "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF",
    "title": "Synthetic title",
}

MAX_TITLE_CHARACTERS = 255

_RENAME = "rename"
_DO_NOT_RENAME = "do not rename"
_NOTHING_RENAMED = "The page was not renamed."

_UNTITLED_PAGE = "an untitled page"
_UNNAMED_NOTEBOOK = "an unnamed notebook"

_DESCRIPTION = """\
Changes the title of one page and nothing else. onenote_edit_page is the sibling for the body. \
OneNote can show the change to everyone who opens the notebook.

Notes:
- This tool asks the user to agree before it writes into a notebook that is shared with other \
people or belongs to somebody else. A page in the user's own unshared notebook is renamed without \
a question.
- This call is safe to repeat after a timeout. The answer's `previous_title` comes from the page \
index, which can lag, so it can be stale or empty.
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

_WRITTEN_BUT_UNREAD = (
    "The rename reached Microsoft 365 and was applied: only the read back that confirms it "
    + "failed afterward. Read the page with onenote_read_page to see the new title. Calling "
    + "onenote_rename_page again with the same title is harmless — it sets the title to the "
    + "same value rather than piling up a second change — so retry it once if you need the "
    + "answer this call could not give you."
)


class RenamedPage(BaseModel):
    page: PageSummary = Field(
        description=(
            "The page as the page index holds it right after the rename. Its "
            + "`last_modified_at` can still show the earlier value, because the page index can "
            + "lag an edit by minutes or by days."
        )
    )
    previous_title: str | None = Field(
        description=(
            "The title the page index held for this page immediately before the rename, read "
            + "before the write. Null when Graph did not report one."
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
    summary: PageSummary | None = None
    previous_title: str | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        pre_read = await page_for_a_question(client, handle.page_id)
        previous_title = pre_read.page.title
        if answer_pending or pre_read.audience.reaches_others:
            with not_graph():
                answer = await confirm(_question(pre_read.page, title, pre_read.audience), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_RENAME_PAGE):
                await _rename(client, handle, title)
            try:
                summary = await page_summary(client, handle.page_id)
            except GraphFailure as failure:
                raise ToolError(_WRITTEN_BUT_UNREAD) from failure

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert summary is not None, "a write neither asked about nor refused wrote nothing"
    return RenamedPage(page=summary, previous_title=previous_title)


def _question(page: OnenotePage, title: str, audience: NotebookAudience) -> str:
    old = page.title or _UNTITLED_PAGE
    name = audience.name or _UNNAMED_NOTEBOOK
    reason = f", {audience.reason}" if audience.reaches_others else ""
    return f"Rename the page {old!r} to {title!r} in the notebook {name!r}{reason}?"


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_RENAME, decline=_DO_NOT_RENAME, nothing_happened=_NOTHING_RENAMED
    )


async def _rename(client: GraphServiceClient, handle: OnenotePageHandle, title: str) -> None:
    command = OnenotePatchContentCommand(
        target="title", action=OnenotePatchActionType.Replace, content=escape(title)
    )
    body = _post_request_body.OnenotePatchContentPostRequestBody(commands=[command])
    await client.me.onenote.pages.by_onenote_page_id(handle.page_id).onenote_patch_content.post(
        body
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Rename a Page",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def onenote_rename_page(
        page: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The page to rename: the `uri` of a onenote_list_pages row or a "
                    + "onenote_create_page answer, copied word for word. The shape is "
                    + "onenote:///pages/{id}. A section handle is not a page handle."
                ),
            ),
        ],
        title: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_TITLE_CHARACTERS,
                description=(
                    "The page's new title, as the user writes it. The answer's `title` is what "
                    + "Microsoft stored. Read it from the answer, not from this argument."
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
