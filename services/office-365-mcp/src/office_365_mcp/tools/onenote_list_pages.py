from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.onenote_page_collection_response import (
    OnenotePageCollectionResponse,
)
from msgraph.generated.users.item.onenote.pages.pages_request_builder import (
    PagesRequestBuilder as _TopPagesRequestBuilder,
)
from msgraph.generated.users.item.onenote.sections.item.pages.pages_request_builder import (
    PagesRequestBuilder as _SectionPagesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
from office_365_mcp.shared.handles import OnenoteSectionHandle, onenote_section_handle
from office_365_mcp.shared.notes import PAGE_EXPANSIONS, PAGE_FIELDS, PageSummary
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "onenote_list_pages"

STEP_PAGES = "pages"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not list these pages. If this call named a `section`, the handle is "
    + "well formed, so the section was most likely deleted, or moved to a different notebook, "
    + "which gives it a new handle: call onenote_list_notebooks again and take a fresh `uri` for "
    + "the section from there, because this same handle fails again. If it named none, Microsoft "
    + "found no OneNote for this account to list pages from at all, and no other argument here "
    + "fixes that."
)

MAX_PAGES = 100

_MIN_TITLE_FRAGMENT_CHARACTERS = 1
_MAX_TITLE_FRAGMENT_CHARACTERS = 200

_PagesQuery = _TopPagesRequestBuilder.PagesRequestBuilderGetQueryParameters
_SectionPagesQuery = _SectionPagesRequestBuilder.PagesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Find pages across the signed-in user's OneNote notebooks, or inside one section. Omit `section` \
to search every page of every notebook the user owns and every notebook shared with them. Pass a \
section's `uri` from an onenote_list_notebooks result as `section` to search only that one \
section's pages. `title_contains` keeps only the pages whose TITLE holds this text, compared \
without regard to case. It matches the title alone. A page created or renamed in the last \
minutes can be missed, because Microsoft's page index lags an edit and holds an empty title \
until it catches up. Microsoft Graph has no full-text search over \
the words inside a OneNote page for a work or school account, so no value here reaches what a \
page says, only what it is called. Leave `title_contains` out to list pages instead of searching \
for one. Rows come back newest change first, and there is no way to ask for a different order. \
Each row carries a `uri`: pass it to onenote_read_page to read that page. Each row also carries a \
`section_uri`: pass it back to onenote_list_pages to see that page's siblings, or to \
onenote_create_page to add a page beside it.\
"""

_NOT_A_SECTION_HANDLE = (
    "onenote_list_pages takes a section handle in `section`. It looks like "
    + "onenote:///sections/{id}, and it comes from the `uri` of a section in an "
    + "onenote_list_notebooks result. Copy it exactly. A section's name is not a handle, nor is "
    + "a notebook's name, nor a web address, nor a bare section id. A page handle "
    + "(onenote:///pages/{id}) is not one either, because a page holds no pages of its own to "
    + "list. Omit `section` to search every notebook the user owns and every notebook shared "
    + "with them instead. This same value fails again, so do not retry it."
)


class PageList(BaseModel):
    pages: list[PageSummary] = Field(
        description=(
            "The pages that matched, newest change first. An empty list means nothing matched, "
            + "or the section holds no pages at all. Microsoft sometimes returns a page with no "
            + "id; this connector cannot address such a page again, so it leaves it out instead "
            + "of giving a handle that fails."
        )
    )
    capped: bool = Field(
        description=(
            "True when `limit` stopped this search while Microsoft still had more matching "
            + "pages to give. Ask again with a higher `limit` to see more of them. False when "
            + "the search ended on its own, however few pages came back."
        )
    )


async def list_pages(
    client: GraphServiceClient,
    *,
    section: str | None = None,
    title_contains: str | None = None,
    limit: int,
) -> PageList:
    assert 1 <= limit <= MAX_PAGES, f"limit must be within 1..{MAX_PAGES}, got {limit}"
    handle = _section_to_search(section)
    query_filter = _title_filter(title_contains)

    with graph_errors(TOOL_NAME), graph_step(STEP_PAGES):
        first_page = await _first_page(client, handle, limit=limit, query_filter=query_filter)
        assert first_page is not None, "Graph answered a page listing with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return PageList(
        pages=[row for page in collected.items if (row := PageSummary.from_page(page)) is not None],
        capped=collected.capped,
    )


def _section_to_search(section: str | None) -> OnenoteSectionHandle | None:
    if section is None:
        return None
    handle = onenote_section_handle(section)
    if handle is None:
        raise ToolError(_NOT_A_SECTION_HANDLE)
    return handle


def _title_filter(title_contains: str | None) -> str | None:
    if title_contains is None:
        return None
    literal = odata_literal(title_contains.lower())
    return f"contains(tolower(title),'{literal}')"


async def _first_page(
    client: GraphServiceClient,
    section: OnenoteSectionHandle | None,
    *,
    limit: int,
    query_filter: str | None,
) -> OnenotePageCollectionResponse | None:
    if section is None:
        return await client.me.onenote.pages.get(
            request_configuration=RequestConfiguration[_PagesQuery](
                query_parameters=_PagesQuery(
                    select=list(PAGE_FIELDS),
                    expand=list(PAGE_EXPANSIONS),
                    top=limit,
                    filter=query_filter,
                )
            )
        )
    return await client.me.onenote.sections.by_onenote_section_id(section.section_id).pages.get(
        request_configuration=RequestConfiguration[_SectionPagesQuery](
            query_parameters=_SectionPagesQuery(
                select=list(PAGE_FIELDS),
                expand=list(PAGE_EXPANSIONS),
                top=limit,
                filter=query_filter,
            )
        )
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Find Pages",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def onenote_list_pages(
        section: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Search only this section's pages, as the `uri` of a section in an "
                    + "onenote_list_notebooks result: onenote:///sections/{id}. Omit it to "
                    + "search across every notebook the user owns and every notebook shared "
                    + "with them. A section's name, a notebook's name and a page handle are "
                    + "none of them section handles."
                ),
            ),
        ] = None,
        title_contains: Annotated[
            str | None,
            Field(
                min_length=_MIN_TITLE_FRAGMENT_CHARACTERS,
                max_length=_MAX_TITLE_FRAGMENT_CHARACTERS,
                description=(
                    "Keep only the pages whose TITLE contains this text, compared without "
                    + "regard to case. This matches the title alone, and a page created or "
                    + "renamed in the last minutes can be missed, because Microsoft's page index "
                    + "lags an edit and holds an empty title until it catches up. Microsoft Graph "
                    + "has no "
                    + "full-text search over what a OneNote page says for a work or school "
                    + "account, so no value here reaches the words inside a page, only its "
                    + "title. Omit it to list pages instead of searching for one."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_PAGES,
                description=(
                    f"How many pages to return, at most {MAX_PAGES}. Paging happens inside "
                    + "the call, so this is the whole answer rather than a first page: raise "
                    + "it rather than calling again with the same arguments. Rows come back "
                    + "newest change first; `capped` says whether this limit stopped the "
                    + "search early."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> PageList:
        return await list_pages(client, section=section, title_contains=title_contains, limit=limit)
