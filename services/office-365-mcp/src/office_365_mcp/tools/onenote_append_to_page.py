from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.models.onenote_patch_action_type import OnenotePatchActionType
from msgraph.generated.models.onenote_patch_content_command import OnenotePatchContentCommand
from msgraph.generated.models.onenote_patch_insert_position import OnenotePatchInsertPosition
from msgraph.generated.users.item.onenote.pages.item.onenote_patch_content import (
    onenote_patch_content_post_request_body as _post_request_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import OnenotePageHandle, onenote_page_handle
from office_365_mcp.shared.notes import (
    NotebookAudience,
    PageSummary,
    page_for_a_question,
    page_summary,
    write_state_for,
)
from office_365_mcp.shared.prose import body_opening
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "onenote_append_to_page"

STEP_APPEND_CONTENT = "append_content"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "page": "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF",
    "body_html": "<p>Synthetic.</p>",
}

MAX_BODY_CHARACTERS = 500_000

_APPEND = "append"
_DO_NOT_APPEND = "do not append"
_NOTHING_APPENDED = "Nothing was appended."

_UNTITLED_PAGE = "an untitled page"
_UNNAMED_NOTEBOOK = "an unnamed notebook"

_DESCRIPTION = """\
Adds HTML to the end of one page. It changes nothing that is already there: it cannot insert in \
the middle, edit a word, or delete. onenote_edit_page is the sibling for those changes. OneNote \
can show the change to everyone who opens the notebook.

Notes:
- This tool asks the user to agree before it writes into a notebook that is shared with other \
people or belongs to somebody else. A page in the user's own unshared notebook is appended to \
without a question.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
onenote_read_page does not already show the block.
"""

_NOT_A_PAGE_HANDLE = (
    "onenote_append_to_page takes a page handle. It looks like onenote:///pages/{id}, with the "
    + "id percent-encoded, for example "
    + "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF. A section handle "
    + "(onenote:///sections/{id}) is not a page handle: it names a whole section, not one page "
    + "inside it. A page title, a web address, and a bare id with no scheme are not handles "
    + "either. Take the `uri` from a onenote_list_pages row or a onenote_create_page answer, "
    + "and copy it word for word. This same value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 could not complete this append. The handle is well formed, so the argument "
    + "is not the problem. The page was most likely deleted or moved to another section, "
    + "either of which gives it a new id that this handle does not name — or the notebook "
    + "holding the page could not be read. Either way, nothing was appended. Find the page "
    + "again with onenote_list_pages, and take the `uri` from that new result. This same "
    + "handle fails the same way every time, so do not retry it."
)

_WRITTEN_BUT_UNREAD = (
    "The append reached Microsoft 365 and was applied to the page: only the read back that "
    + "confirms it failed afterward. Read the page with onenote_read_page to see the new "
    + "content. Calling onenote_append_to_page again for this same reason adds the same text a "
    + "second time, so do not retry it — retry only if the append itself times out."
)


async def append_to_page(
    client: GraphServiceClient,
    *,
    page: str,
    body_html: str,
    confirm: Confirm,
    answer_pending: bool = False,
) -> PageSummary | InputRequiredResult:
    handle = onenote_page_handle(page)
    if handle is None:
        raise ToolError(_NOT_A_PAGE_HANDLE)

    about = write_state_for(_APPEND, handle.page_id, body_html)
    summary: PageSummary | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        pre_read = await page_for_a_question(client, handle.page_id)
        if answer_pending or pre_read.audience.reaches_others:
            with not_graph():
                answer = await confirm(
                    _question(pre_read.page, pre_read.audience, body_html), about
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_APPEND_CONTENT):
                await _append(client, handle, body_html=body_html)
            try:
                summary = await page_summary(client, handle.page_id)
            except GraphFailure as failure:
                raise ToolError(_WRITTEN_BUT_UNREAD) from failure

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert summary is not None, "a write neither asked about nor refused wrote nothing"
    return summary


def _question(page: OnenotePage, audience: NotebookAudience, body_html: str) -> str:
    title = page.title or _UNTITLED_PAGE
    name = audience.name or _UNNAMED_NOTEBOOK
    opening = body_opening(body_html)
    return (
        f"Append to the page {title!r} in the notebook {name!r}, {audience.reason}? "
        + f"The new text opens {opening!r}."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_APPEND, decline=_DO_NOT_APPEND, nothing_happened=_NOTHING_APPENDED
    )


async def _append(client: GraphServiceClient, handle: OnenotePageHandle, *, body_html: str) -> None:
    command = OnenotePatchContentCommand(
        target="body",
        action=OnenotePatchActionType.Append,
        position=OnenotePatchInsertPosition.After,
        content=body_html,
    )
    await client.me.onenote.pages.by_onenote_page_id(handle.page_id).onenote_patch_content.post(
        _post_request_body.OnenotePatchContentPostRequestBody(commands=[command]),
        request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Append to a Page",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def onenote_append_to_page(
        page: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The page to add to: the `uri` of a onenote_list_pages row or a "
                    + "onenote_create_page answer, copied word for word. The shape is "
                    + "onenote:///pages/{id}. A section handle is not a page handle."
                ),
            ),
        ],
        body_html: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_BODY_CHARACTERS,
                description=(
                    "The HTML to add after everything already on the page. A newline is not a "
                    + "line break. Write `<p>`, `<br>`, `<h1>` to `<h6>`, `<ul>`, `<ol>`, `<li>`, "
                    + "`<table>`, `<b>` and `<i>` for structure. Microsoft removes JavaScript, "
                    + "CSS and forms. Escape `&`, `<` and `>` where they must read as themselves. "
                    + "No argument here attaches a file or an image."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> PageSummary | InputRequiredResult:
        return await append_to_page(
            client,
            page=page,
            body_html=body_html,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
