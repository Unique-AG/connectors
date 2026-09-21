from collections.abc import Mapping
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, not_graph
from office_365_mcp.shared.handles import OnenoteSectionHandle, onenote_page_handle
from office_365_mcp.shared.notes import NotebookAudience, page_for_a_question, write_state_for
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "onenote_delete_page"

STEP_DELETE_PAGE = "delete_page"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "page": "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF",
}

_DELETE = "delete"
_KEEP_THE_PAGE = "keep the page"
_NOTHING_DELETED = "The page was not deleted."

_UNTITLED_PAGE = "an untitled page"
_UNNAMED_NOTEBOOK = "an unnamed notebook"
_UNNAMED_SECTION = "an unnamed section"

_DESCRIPTION = """\
Delete an existing OneNote page outright. Pass the `page` handle from a onenote_list_pages row \
or a onenote_create_page answer. This tool ALWAYS asks the person at the other end to confirm \
before deleting, whatever notebook the page is in and whoever can see it, because a delete \
cannot be undone: Microsoft Graph gives OneNote no recycle bin, no trash, and no way for this \
connector to bring a deleted page back. A decline leaves the page exactly as it was. Once this \
tool answers, the `page` handle it was given addresses nothing: Microsoft Graph answers 404 to \
it from that moment on, and no other onenote_* tool — not onenote_read_page, not \
onenote_edit_page, not onenote_rename_page, not this tool called again — can reach that page a \
second time. This call is safe to retry after a timeout: if Microsoft already deleted the page \
before the response was lost, the retry finds nothing there and reports that plainly rather \
than deleting a second time, because there is nothing left to delete twice.\
"""

_NOT_A_PAGE_HANDLE = (
    "onenote_delete_page takes a page handle. It looks like onenote:///pages/{id}, with the id "
    + "percent-encoded, for example "
    + "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF. A section handle "
    + "(onenote:///sections/{id}) is not a page handle: it names a whole section, not one page "
    + "inside it. A page title, a web address, and a bare id with no scheme are not handles "
    + "either. Take the `uri` from a onenote_list_pages row or a onenote_create_page answer, "
    + "and copy it word for word. This same value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 has no such page to delete. It is most likely already gone — deleted a "
    + "moment ago by this same call after a lost response, deleted some other way, or moved to "
    + "another section, which gives it a new id this handle does not name. Either way, nothing "
    + "was deleted by this call. If the page still needs to go, find it again with "
    + "onenote_list_pages and take a fresh `uri` from that result; if it does not turn up there "
    + "either, it is already gone and there is nothing left to delete. This same handle fails "
    + "the same way every time, so do not retry it unchanged."
)


class DeletedPage(BaseModel):
    title: str | None = Field(
        description=(
            "The title Microsoft's page index held for this page just before the delete. Can "
            + "be stale or empty, because that index lags a create or an edit. Null when Graph "
            + "reported none."
        )
    )
    section_uri: str | None = Field(
        description=(
            "The handle of the section that held this page: onenote:///sections/{id}. Null "
            + "when Graph named no parent section."
        )
    )
    section_name: str | None = Field(
        description=(
            "The display name of the section that held this page. Null when Graph named no "
            + "parent section."
        )
    )
    notebook_name: str | None = Field(
        description=(
            "The display name of the notebook that held this page. Null when Graph named no "
            + "parent notebook."
        )
    )
    deleted: Literal[True] = Field(
        description=(
            "Always true: this tool answers only once the delete has actually succeeded, never "
            + "with a page that is still there. The `page` handle this call was given now "
            + "addresses nothing — Microsoft Graph answers 404 to it from this point on, and no "
            + "onenote_* tool can read, edit, rename or delete it again."
        )
    )


async def delete_page(
    client: GraphServiceClient, *, page: str, confirm: Confirm
) -> DeletedPage | InputRequiredResult:
    handle = onenote_page_handle(page)
    if handle is None:
        raise ToolError(_NOT_A_PAGE_HANDLE)

    about = write_state_for(_DELETE, handle.page_id)
    found: OnenotePage | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        pre_read = await page_for_a_question(client, handle.page_id)
        found = pre_read.page
        with not_graph():
            answer = await confirm(_question(found, pre_read.audience), about)
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_DELETE_PAGE):
                await client.me.onenote.pages.by_onenote_page_id(handle.page_id).delete()

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert found is not None, "a delete neither asked about nor refused deleted nothing"
    return _answer(found)


def _question(page: OnenotePage, audience: NotebookAudience) -> str:
    title = page.title or _UNTITLED_PAGE
    section = page.parent_section
    section_label = (section.display_name if section is not None else None) or _UNNAMED_SECTION
    name = audience.name or _UNNAMED_NOTEBOOK
    reason = f", {audience.reason}" if audience.reaches_others else ""
    return (
        f"Delete the page {title!r} from the section {section_label!r} of the notebook "
        + f"{name!r}{reason}? Microsoft Graph has no recycle bin for a page: this cannot be "
        + "undone."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_DELETE, decline=_KEEP_THE_PAGE, nothing_happened=_NOTHING_DELETED
    )


def _answer(page: OnenotePage) -> DeletedPage:
    section = page.parent_section
    section_id = section.id if section is not None else None
    notebook = page.parent_notebook
    return DeletedPage(
        title=page.title,
        section_uri=None if section_id is None else OnenoteSectionHandle(section_id).uri,
        section_name=section.display_name if section is not None else None,
        notebook_name=notebook.display_name if notebook is not None else None,
        deleted=True,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Delete a Page",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def onenote_delete_page(
        page: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the page to delete, from a onenote_list_pages row or a "
                    + "onenote_create_page answer: `uri`, copied word for word. The shape is "
                    + "onenote:///pages/{id}. A section handle, onenote:///sections/{id}, is "
                    + "not a page handle. Never build one yourself: a page id alone, without "
                    + "this connector's scheme around it, reaches nothing."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedPage | InputRequiredResult:
        return await delete_page(client, page=page, confirm=a_person_agrees(ctx))
