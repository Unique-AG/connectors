from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.generated.models.onenote_patch_action_type import OnenotePatchActionType
from msgraph.generated.models.onenote_patch_content_command import OnenotePatchContentCommand
from msgraph.generated.models.onenote_patch_insert_position import OnenotePatchInsertPosition
from msgraph.generated.users.item.onenote.pages.item.onenote_page_item_request_builder import (
    OnenotePageItemRequestBuilder,
)
from msgraph.generated.users.item.onenote.pages.item.onenote_patch_content import (
    onenote_patch_content_post_request_body as _post_request_body,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry
from office_365_mcp.shared.handles import OnenotePageHandle, onenote_page_handle
from office_365_mcp.shared.notes import PAGE_EXPANSIONS, PAGE_FIELDS, PageSummary
from office_365_mcp.shared.seam import WRITE_ADDITIVE, graph_client_for_caller

TOOL_NAME = "onenote_append_to_page"

STEP_APPEND_CONTENT = "append_content"
STEP_PAGE = "page"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "page": "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF",
    "body_html": "<p>Synthetic.</p>",
}

MAX_BODY_CHARACTERS = 500_000

_PageQuery = OnenotePageItemRequestBuilder.OnenotePageItemRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Add HTML to the very END of an existing OneNote page's body. Pass the `page` handle from a \
onenote_list_pages row or a onenote_create_page answer. This tool changes NOTHING that is \
already on the page: it cannot insert content in the middle of the page, cannot edit a single \
word that is already there, and cannot delete anything. It only ever adds new content after \
everything else, the way writing at the bottom of a piece of paper does. Nobody is notified: \
OneNote sends no alert to anyone when a page changes. `body_html` is HTML: write `<p>`, `<br>`, \
`<ul>`/`<ol>`/`<li>` and `<table>`/`<tr>`/`<td>` for structure, and escape `&`, `<` and `>` \
where they must read as themselves. Microsoft strips any `<script>` tag and any CSS out of what \
you send, and removes an HTML form entirely, so neither one ever reaches the page. There is no \
argument here that attaches a file or an image, and that absence is deliberate: this connector \
has no content store, and offering one would let a model attach whatever it chose. This call is \
NOT SAFE TO RETRY BLINDLY: if it times out, Microsoft may already hold the append, and calling \
it again with the same `body_html` adds a second copy of it to the page. On a timeout, read the \
page first with onenote_read_page and look for the block you meant to add; call this tool again \
only when that block is not there. This tool answers with the page as Microsoft's page index \
holds it right after the write. That index lags an edit by minutes, so `last_modified_at` and \
`title` in the answer can still show the values from before this write while onenote_read_page \
already returns the appended block.\
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
    "Microsoft 365 did not find this page. The handle is well formed, so the argument is not "
    + "the problem. The page was most likely deleted, or moved to another section, and either "
    + "one gives it a new id that this handle does not name. Nothing was appended. Find the "
    + "page again with onenote_list_pages, and take the `uri` from that new result. This same "
    + "handle fails the same way every time, so do not retry it."
)


async def append_to_page(client: GraphServiceClient, *, page: str, body_html: str) -> PageSummary:
    handle = onenote_page_handle(page)
    if handle is None:
        raise ToolError(_NOT_A_PAGE_HANDLE)

    with graph_errors(TOOL_NAME):
        with graph_step(STEP_APPEND_CONTENT):
            await _append(client, handle, body_html=body_html)
        with graph_step(STEP_PAGE):
            refreshed = await _page(client, handle)

    summary = PageSummary.from_page(refreshed)
    assert summary is not None, "Graph re-read a page it gave no id, which cannot be addressed"
    return summary


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
                    "The handle of the page to add to, from a onenote_list_pages row or a "
                    + "onenote_create_page answer: `uri`, copied word for word. The shape is "
                    + "onenote:///pages/{id}. A section handle, onenote:///sections/{id}, is not "
                    + "a page handle. Never build one yourself: a page id alone, without this "
                    + "connector's scheme around it, reaches nothing."
                ),
            ),
        ],
        body_html: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_BODY_CHARACTERS,
                description=(
                    "The HTML to add after everything already on the page. Write `<p>` and "
                    + "`<br>` for structure, `<ul>`/`<ol>`/`<li>` for lists, and "
                    + "`<table>`/`<tr>`/`<td>` for tables. Escape `&`, `<` and `>` where they "
                    + "must read as themselves. Microsoft strips `<script>` tags and CSS out of "
                    + "this before it reaches the page, and removes an HTML form entirely. There "
                    + "is no way to attach a file or an image here; that absence is deliberate."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> PageSummary:
        return await append_to_page(client, page=page, body_html=body_html)
