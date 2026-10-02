from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.onenote_page_collection_response import (
    OnenotePageCollectionResponse,
)
from msgraph.generated.users.item.onenote.pages.pages_request_builder import PagesRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
from office_365_mcp.shared.handles import (
    OnenoteOwner,
    OnenoteSectionHandle,
    onenote_section_handle,
)
from office_365_mcp.shared.notes import (
    OWNED_REFUSED,
    PAGE_EXPANSIONS,
    PAGE_FIELDS,
    PageSummary,
    get_with_query,
    onenote_root,
    owner_named,
)
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller, owner_refused
from office_365_mcp.shared.window import closes_at, opens_at, runs_backwards

TOOL_NAME = "onenote_list_pages"

STEP_PAGES = "pages"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Notes.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not list these pages. If this call named a `section`, the handle is "
    + "well formed, so the section was most likely deleted, or moved to a different notebook, "
    + "which gives it a new handle: call onenote_list_notebooks again and take a fresh `uri` for "
    + "the section from there, because this same handle fails again. If this call named a "
    + "`group`, the id most likely names no group that the signed-in user can reach. Ask the "
    + "user for the correct id. This same id fails again, so do not retry it. If this call "
    + "named a `site`, the id most likely names no site that the "
    + "signed-in user can reach. Ask the user for the correct id. This same id fails again, so "
    + "do not retry it. If it named none of these, Microsoft found no OneNote for this account "
    + "to list pages from at all, and no other argument here fixes that."
)

_OWNER_REFUSED = (
    "Microsoft 365 refused this request for the `group` or the `site` that this call named. "
    + "Most likely, the signed-in user is not a member of that group or site, or the id is "
    + "wrong. Ask the user for the correct id, or ask them to get access. If this tool also fails "
    + "without `group` and `site`, ask a Microsoft 365 administrator to grant the delegated "
    + "permission Notes.Read. If the user already has access, ask an administrator to examine "
    + "the OneNote permissions of this connector. This same call fails again, so do not retry it."
)

MAX_PAGES = 100

_MIN_TITLE_FRAGMENT_CHARACTERS = 1

_PagesQuery = PagesRequestBuilder.PagesRequestBuilderGetQueryParameters

_LEVEL_AND_ORDER_FIELDS: tuple[str, ...] = ("level", "order")

OrderBy = Literal[
    "last_modified_desc",
    "last_modified_asc",
    "created_desc",
    "created_asc",
    "title_asc",
    "title_desc",
]

_ORDER_BY_CLAUSES: Mapping[str, str] = {
    "last_modified_desc": "lastModifiedDateTime desc",
    "last_modified_asc": "lastModifiedDateTime asc",
    "created_desc": "createdDateTime desc",
    "created_asc": "createdDateTime asc",
    "title_asc": "title asc",
    "title_desc": "title desc",
}

_DESCRIPTION = """\
Finds pages across every notebook the signed-in user can reach, inside one section, or inside the \
notebooks of one group or one SharePoint site. `title_contains` matches the title only: Microsoft \
Graph has no full-text search over a page's words for a work or school account. The page index can \
hold an empty title for days after a create, so find a new page by `created_at` or by its section \
instead.

Notes:
- The four date windows are inclusive at both ends and combine with AND. The default order is \
newest change first.
"""

_NOT_A_SECTION_HANDLE = (
    "onenote_list_pages takes a section handle in `section`. It looks like "
    + "onenote:///sections/{id}, and it comes from the `uri` of a section in an "
    + "onenote_list_notebooks result. A handle from a group or site notebook starts with "
    + "onenote:///groups/{group}/ or onenote:///sites/{site}/ instead. Copy it exactly. A "
    + "section's name is not a handle, nor is a notebook's name, nor a web address, nor a bare "
    + "section id. A page handle (onenote:///pages/{id}) is not one either, because a page holds "
    + "no pages of its own to list. Omit `section` to search every notebook the user owns and "
    + "every notebook shared with them instead. This same value fails again, so do not retry it."
)

_PAGELEVEL_NEEDS_A_SECTION = (
    "onenote_list_pages only fills `level` and `order` for one section's pages at a time: "
    + "Microsoft Graph computes them only on `../sections/{id}/pages`, never on a search across "
    + "every notebook. Pass a section's `uri` from an onenote_list_notebooks result as `section` "
    + "alongside `include_level_and_order=true`, or drop `include_level_and_order` to search "
    + "every notebook without it. The same combination fails again, so do not retry it as it is."
)

_GROUP_WITH_A_SECTION = (
    "onenote_list_pages takes `group` or `site` only when `section` is omitted. A section handle "
    + "from a group or site notebook already carries its owner. The same combination fails "
    + "again, so do not retry it as it is."
)

_GROUP_WITH_A_SITE = (
    "onenote_list_pages takes at most one of `group` and `site`. A notebook belongs to one group "
    + "or one site, never to both. The same combination fails again, so do not retry it as it is."
)

_MODIFIED_WINDOW_RUNS_BACKWARDS = (
    "onenote_list_pages found nothing, because `modified_before` falls before `modified_after`, "
    + "and no section or notebook holds a window that runs backwards. A date covers the whole of "
    + "the day it names at either end, so one date in both bounds searches that single day. Put "
    + "the earlier point in `modified_after` and the later one in `modified_before`, then call "
    + "again. The same two values will fail the same way."
)

_CREATED_WINDOW_RUNS_BACKWARDS = (
    "onenote_list_pages found nothing, because `created_before` falls before `created_after`, "
    + "and no section or notebook holds a window that runs backwards. A date covers the whole of "
    + "the day it names at either end, so one date in both bounds searches that single day. Put "
    + "the earlier point in `created_after` and the later one in `created_before`, then call "
    + "again. The same two values will fail the same way."
)


class PageList(BaseModel):
    pages: list[PageSummary] = Field(
        description=(
            "The pages that matched, in the order this call asked for. An empty list means "
            + "nothing matched, or the section holds no pages at all. A page with no id from "
            + "Microsoft is left out. It never gets a handle that fails."
        )
    )
    capped: bool = Field(
        description=(
            "True when `limit` stopped this search while more pages matched. Raise `limit` "
            + f"while it is below {MAX_PAGES}. At {MAX_PAGES}, call again with `skip` set to the "
            + "number of rows already returned. False when the search ended on its own."
        )
    )


async def list_pages(
    client: GraphServiceClient,
    *,
    section: str | None = None,
    group: str | None = None,
    site: str | None = None,
    title_contains: str | None = None,
    created_by_app_id: str | None = None,
    order_by: OrderBy | None = None,
    modified_after: date | datetime | None = None,
    modified_before: date | datetime | None = None,
    created_after: date | datetime | None = None,
    created_before: date | datetime | None = None,
    skip: int = 0,
    include_level_and_order: bool = False,
    limit: int,
) -> PageList:
    assert 1 <= limit <= MAX_PAGES, f"limit must be within 1..{MAX_PAGES}, got {limit}"
    assert skip >= 0, f"skip must not be negative, got {skip}"
    if group is not None and site is not None:
        raise ToolError(_GROUP_WITH_A_SITE)
    if section is not None and (group is not None or site is not None):
        raise ToolError(_GROUP_WITH_A_SECTION)
    handle = _section_to_search(section)
    owner = owner_named(group=group, site=site) if handle is None else handle.owner
    if include_level_and_order and handle is None:
        raise ToolError(_PAGELEVEL_NEEDS_A_SECTION)
    _refuse_backwards_windows(modified_after, modified_before, created_after, created_before)
    query_filter = _filter(
        title_contains,
        created_by_app_id,
        modified_after,
        modified_before,
        created_after,
        created_before,
    )
    order_clause = _ORDER_BY_CLAUSES[order_by] if order_by is not None else None

    with (
        owner_refused(group is not None or site is not None, _OWNER_REFUSED),
        owner_refused(handle is not None and handle.owner is not None, OWNED_REFUSED),
        graph_errors(TOOL_NAME),
        graph_step(STEP_PAGES),
    ):
        first_page = await _first_page(
            client,
            handle,
            owner,
            limit=limit,
            query_filter=query_filter,
            order_by=order_clause,
            skip=skip,
            include_level_and_order=include_level_and_order,
        )
        assert first_page is not None, "Graph answered a page listing with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return PageList(
        pages=[
            row
            for page in collected.items
            if (row := PageSummary.from_page(page, owner=owner)) is not None
        ],
        capped=collected.capped,
    )


def _section_to_search(section: str | None) -> OnenoteSectionHandle | None:
    if section is None:
        return None
    handle = onenote_section_handle(section)
    if handle is None:
        raise ToolError(_NOT_A_SECTION_HANDLE)
    return handle


def _refuse_backwards_windows(
    modified_after: date | datetime | None,
    modified_before: date | datetime | None,
    created_after: date | datetime | None,
    created_before: date | datetime | None,
) -> None:
    if runs_backwards(modified_after, modified_before):
        raise ToolError(_MODIFIED_WINDOW_RUNS_BACKWARDS)
    if runs_backwards(created_after, created_before):
        raise ToolError(_CREATED_WINDOW_RUNS_BACKWARDS)


def _title_filter(title_contains: str | None) -> str | None:
    if title_contains is None:
        return None
    literal = odata_literal(title_contains.lower())
    return f"contains(tolower(title),'{literal}')"


def _opening_term(property_name: str, after: date | datetime) -> str:
    return f"{property_name} ge {_wire(opens_at(after))}"


def _closing_term(property_name: str, before: date | datetime) -> str:
    if isinstance(before, datetime):
        return f"{property_name} le {_wire(closes_at(before))}"
    return f"{property_name} lt {_wire(opens_at(before + timedelta(days=1)))}"


def _wire(instant: datetime) -> str:
    if instant.microsecond:
        return f"{instant:%Y-%m-%dT%H:%M:%S.%f}Z"
    return f"{instant:%Y-%m-%dT%H:%M:%SZ}"


def _filter(
    title_contains: str | None,
    created_by_app_id: str | None,
    modified_after: date | datetime | None,
    modified_before: date | datetime | None,
    created_after: date | datetime | None,
    created_before: date | datetime | None,
) -> str | None:
    clauses: list[str] = []
    if modified_after is not None:
        clauses.append(_opening_term("lastModifiedDateTime", modified_after))
    if modified_before is not None:
        clauses.append(_closing_term("lastModifiedDateTime", modified_before))
    if created_after is not None:
        clauses.append(_opening_term("createdDateTime", created_after))
    if created_before is not None:
        clauses.append(_closing_term("createdDateTime", created_before))
    title_clause = _title_filter(title_contains)
    if title_clause is not None:
        clauses.append(title_clause)
    if created_by_app_id is not None:
        clauses.append(f"createdByAppId eq '{odata_literal(created_by_app_id)}'")
    return " and ".join(clauses) if clauses else None


async def _first_page(
    client: GraphServiceClient,
    section: OnenoteSectionHandle | None,
    owner: OnenoteOwner | None,
    *,
    limit: int,
    query_filter: str | None,
    order_by: str | None,
    skip: int,
    include_level_and_order: bool,
) -> OnenotePageCollectionResponse | None:
    raw_query: dict[str, str] = {"pagelevel": "true"} if include_level_and_order else {}
    root = onenote_root(client, owner)
    pages = (
        root.pages
        if section is None
        else root.sections.by_onenote_section_id(section.section_id).pages
    )
    fields = (*PAGE_FIELDS, *_LEVEL_AND_ORDER_FIELDS) if include_level_and_order else PAGE_FIELDS
    typed = _PagesQuery(
        select=list(fields),
        expand=list(PAGE_EXPANSIONS),
        top=limit,
        filter=query_filter,
        orderby=[order_by] if order_by is not None else None,
        skip=skip if skip > 0 else None,
    )
    return await get_with_query(
        client, pages, typed, OnenotePageCollectionResponse, query=raw_query
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
                    + "onenote_list_notebooks result: onenote:///sections/{id}. A handle from a "
                    + "group or site notebook starts with onenote:///groups/{group}/ or "
                    + "onenote:///sites/{site}/ instead. A section's name, a notebook's name and a "
                    + "page handle are not section handles."
                ),
            ),
        ] = None,
        group: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The Microsoft 365 group or team whose pages this call searches, as its "
                    + "Graph id. A team id is a group id. Ask the user for it, or copy a team id "
                    + "from an earlier result. Omit it to search every notebook the user owns or "
                    + "that somebody shares with them. Pass it only without `section`."
                ),
            ),
        ] = None,
        site: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The SharePoint site whose pages this call searches, as its Graph site id. "
                    + "It is a host name and two ids, joined by commas, and it is not "
                    + "percent-encoded. Ask the user for it. Pass it only without `section`. "
                    + "Pass at most one of `group` and `site`."
                ),
            ),
        ] = None,
        title_contains: Annotated[
            str | None,
            Field(
                min_length=_MIN_TITLE_FRAGMENT_CHARACTERS,
                description=(
                    "Keep only the pages whose title contains this text, compared without "
                    + "regard to case. Omit it to list every page. Pass it to search for one "
                    + "page instead."
                ),
            ),
        ] = None,
        created_by_app_id: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Keep only the pages that one app created. Pass the `created_by_app_id` of "
                    + "a row from an earlier result. The match is exact and case-sensitive, so "
                    + "copy it word for word. Omit it to list pages from every app."
                ),
            ),
        ] = None,
        order_by: Annotated[
            OrderBy | None,
            Field(
                description=(
                    "Sort the pages that match, instead of the default order. "
                    + "`last_modified_desc`/`last_modified_asc` sorts by when a page last "
                    + "changed. `created_desc`/`created_asc` sorts by when it was created. "
                    + "`title_asc`/`title_desc` sorts by the page's own title. Omit it to keep "
                    + "the default order."
                ),
            ),
        ] = None,
        modified_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Keep only the pages last changed on or after this point, inclusive. A "
                    + "date, `2026-03-04`, opens at the first instant of that whole UTC day. A "
                    + "moment, `2026-03-04T09:00:00Z`, opens at the second it names, and a "
                    + "moment with no zone is read as UTC. Pair it with `modified_before` to "
                    + "close the window."
                )
            ),
        ] = None,
        modified_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Keep only the pages last changed on or before this point, inclusive, in "
                    + "the same two shapes as `modified_after`. A date closes at the end of "
                    + "that UTC day, so the same date in both bounds keeps that one day. A "
                    + "moment closes at the second it names."
                )
            ),
        ] = None,
        created_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Keep only the pages created on or after this point, inclusive, in the "
                    + "same two shapes as `modified_after`. This bounds when the page was first "
                    + "written, not when it last changed. Pair it with `created_before` to "
                    + "close the window."
                )
            ),
        ] = None,
        created_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Keep only the pages created on or before this point, inclusive, in the "
                    + "same two shapes as `modified_after`. A date closes at the end of that "
                    + "UTC day, so the same date in both bounds keeps that one day."
                )
            ),
        ] = None,
        skip: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "How many matching pages to skip before the first one this call returns. 0 "
                    + "starts from the first match. Raise this by the number of rows the last "
                    + "call returned to reach the next page. A value past the number of "
                    + "matches returns an empty list, not an error."
                ),
            ),
        ] = 0,
        include_level_and_order: Annotated[
            bool,
            Field(
                description=(
                    "Fill each row's `level` (how deeply it is indented under another page) "
                    + "and `order` (its position within the section). This works only "
                    + "together with `section`, because Microsoft Graph computes them for one "
                    + "section's pages at a time. Leave it false, the default, to leave "
                    + "`level` and `order` null."
                ),
            ),
        ] = False,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_PAGES,
                description=(
                    f"How many pages to return, at most {MAX_PAGES}. `capped` says whether this "
                    + f"limit stopped the search early. Raise it while it is below {MAX_PAGES}. "
                    + f"At {MAX_PAGES}, call again with `skip` set to the rows already returned."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> PageList:
        return await list_pages(
            client,
            section=section,
            group=group,
            site=site,
            title_contains=title_contains,
            created_by_app_id=created_by_app_id,
            order_by=order_by,
            modified_after=modified_after,
            modified_before=modified_before,
            created_after=created_after,
            created_before=created_before,
            skip=skip,
            include_level_and_order=include_level_and_order,
            limit=limit,
        )
