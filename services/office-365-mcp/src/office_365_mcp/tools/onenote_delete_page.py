from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.generated.models.onenote_page import OnenotePage
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphNotFound, graph_errors, graph_step, not_graph
from office_365_mcp.shared.handles import OnenoteSectionHandle, onenote_page_handle
from office_365_mcp.shared.notes import (
    NotebookAudience,
    onenote_root,
    page_for_a_question,
    write_state_for,
)
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
Deletes one page outright. This tool always asks the user to agree, because this change is \
permanent. Microsoft Graph keeps no recycle bin for a page.

Notes:
- After this tool deletes the page, the page handle names no page. onenote_read_page, \
onenote_edit_page and onenote_rename_page answer 404 for it.
- This call is safe to repeat after a timeout. A second call finds no page and reports that.
"""

_NOT_A_PAGE_HANDLE = (
    "onenote_delete_page takes a page handle. It looks like onenote:///pages/{id}, with the id "
    + "percent-encoded, for example "
    + "onenote:///pages/1-SYNTHETICPAGE00000000000000000000%21ABCDEF. A handle from a group "
    + "notebook starts with onenote:///groups/{group}/ instead. A section handle "
    + "(onenote:///sections/{id}) is not a page handle: it names a whole section, not one page "
    + "inside it. A page title, a web address, and a bare id with no scheme are not handles "
    + "either. Take the `uri` from a onenote_list_pages row or a onenote_create_page answer, "
    + "and copy it word for word. This same value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 has no such page to delete, and this call deleted nothing. It is probably "
    + "already gone: a person or an earlier call deleted it, or it moved to another section. A "
    + "moved page gets a new id, and this handle does not name it.\n\n"
    + "If you must still delete the page, find it again with onenote_list_pages. Then use the "
    + "`uri` from that result. If the page is not in that result, it is already gone and nothing "
    + "is left to delete. If you call this tool again with the same arguments, the call will fail "
    + "the same way."
)


class DeletedPage(BaseModel):
    title: str | None = Field(
        description=(
            "The title the page index held for this page immediately before the delete. It "
            + "can be stale or empty, because the page index can lag a create or an edit. "
            + "Null when Graph did not report one."
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
            "Always true, because this tool answers only when the page is gone. It is also true "
            + "when the page was there at the start of this call, but Graph then found no page to "
            + "delete."
        )
    )


async def delete_page(
    client: GraphServiceClient, *, page: str, confirm: Confirm
) -> DeletedPage | InputRequiredResult:
    handle = onenote_page_handle(page)
    if handle is None:
        raise ToolError(_NOT_A_PAGE_HANDLE)

    about = write_state_for(_DELETE, handle.uri)
    found: OnenotePage | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        pre_read = await page_for_a_question(client, handle.page_id, group_id=handle.group_id)
        found = pre_read.page
        with not_graph():
            answer = await confirm(_question(found, pre_read.audience), about)
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with suppress(GraphNotFound), graph_step(STEP_DELETE_PAGE):
                await (
                    onenote_root(client, handle.group_id)
                    .pages.by_onenote_page_id(handle.page_id)
                    .delete()
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert found is not None, "a delete neither asked about nor refused deleted nothing"
    return _answer(found, group_id=handle.group_id)


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


def _answer(page: OnenotePage, *, group_id: str | None) -> DeletedPage:
    section = page.parent_section
    section_id = section.id if section is not None else None
    notebook = page.parent_notebook
    return DeletedPage(
        title=page.title,
        section_uri=(
            None if section_id is None else OnenoteSectionHandle(section_id, group_id=group_id).uri
        ),
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
                    "The page to delete: the `uri` of a onenote_list_pages row or a "
                    + "onenote_create_page answer, copied word for word. The shape is "
                    + "onenote:///pages/{id}. A handle from a group notebook starts with "
                    + "onenote:///groups/{group}/ instead. A section handle is not a page handle."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedPage | InputRequiredResult:
        return await delete_page(client, page=page, confirm=a_person_agrees(ctx))
