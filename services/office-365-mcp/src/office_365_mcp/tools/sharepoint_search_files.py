from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.aggregation_option import AggregationOption
from msgraph.generated.models.bucket_aggregation_definition import BucketAggregationDefinition
from msgraph.generated.models.bucket_aggregation_sort_property import (
    BucketAggregationSortProperty,
)
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.entity_type import EntityType
from msgraph.generated.models.search_hit import SearchHit
from msgraph.generated.models.search_hits_container import SearchHitsContainer
from msgraph.generated.models.search_query import SearchQuery
from msgraph.generated.models.search_request import SearchRequest
from msgraph.generated.search.query.query_post_request_body import QueryPostRequestBody
from msgraph.generated.search.query.query_post_response import QueryPostResponse
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared import kql
from office_365_mcp.shared.files import DriveItemSummary
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import closes_at, opens_at, runs_backwards

TOOL_NAME = "sharepoint_search_files"

STEP = "file_search"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "budget"}

MAX_RESULTS = 50

_SITE_FIELD = "SPSiteURL"

MAX_SITES = 10

_DESCRIPTION = """\
Search the files and folders the signed-in user can see across OneDrive and SharePoint, ranked \
by Microsoft's search index rather than by name or date, for finding a file or folder by name or \
by the words inside it. `sharepoint_browse_folder` lists everything sitting directly in one \
named folder, including items outside the search index — use it instead when the user names a \
specific folder and wants everything in it.

Notes:
- Every argument beyond `query` narrows the result with AND; each one only ever shrinks the \
answer.
- Results have no sort order; `modified_after` and `modified_before` bound the window without \
ranking it, so they are not a way to ask for the newest file.
- Put the earlier date in `modified_after` and the later one in `modified_before`; a reversed \
pair matches nothing.
"""

_WINDOW_RUNS_BACKWARDS = (
    "sharepoint_search_files searched nothing, because `modified_before` falls before "
    + "`modified_after`, and no drive holds a window that runs backwards. A date covers the whole "
    + "of the day it names at either end, so one date in both bounds searches that single day. "
    + "Put the earlier point in `modified_after` and the later one in `modified_before`, then call "
    + "again. The same two values will fail the same way."
)

_NOTHING_TO_SEARCH_FOR = (
    "sharepoint_search_files searched nothing, because `query` holds no word to look for and no "
    + "other argument was given. Punctuation and quote marks alone are not a search term. Put the "
    + "words the question is about in `query`, then call again."
)


class SiteMatches(BaseModel):
    """One site, and how many of the matches sit on it."""

    url: str = Field(
        description=(
            "The site's web address. Pass it back as `path` to search only this site; it is "
            + "already in the shape `path` expects."
        )
    )
    match_count: int = Field(
        description=(
            "How many matches sit on this site, counted across every match — not only the ones "
            + "on this page."
        )
    )


class FileSearchResults(BaseModel):
    """One page of matches, the sites they sit on, and the offset that reaches the next page."""

    files: list[DriveItemSummary] = Field(
        description=(
            "The files and folders that matched, on this page. Empty means no match on this "
            + "page, not proof the file doesn't exist elsewhere. A row Graph reported with no "
            + "drive is dropped, because this tool cannot address it again."
        )
    )
    sites: list[SiteMatches] = Field(
        description=(
            "The sites the matches sit on, ranked by match count and counted across every "
            + "match, not only this page — so it shows where the answer lives before paging "
            + "through it. Empty when every match is in the user's own OneDrive, or when the "
            + "organization's search settings disable grouping; never a sign the matches have "
            + "no site."
        )
    )
    next_offset: int | None = Field(
        description=(
            "The offset that reaches the next page, or null when the page cannot advance "
            + "further — either no more results exist, or none of this page's hits could "
            + "advance past. Do not request this same offset again either way. It counts "
            + "Graph's hits, not the rows this tool returned."
        )
    )


async def sharepoint_search_files(
    client: GraphServiceClient,
    *,
    query: str,
    file_type: str | None = None,
    path: str | None = None,
    modified_after: date | datetime | None = None,
    modified_before: date | datetime | None = None,
    offset: int,
    limit: int,
) -> FileSearchResults:
    assert 1 <= limit <= MAX_RESULTS, f"limit is bounded by the schema, got {limit}"
    assert offset >= 0, f"offset must not be negative, got {offset}"
    if runs_backwards(modified_after, modified_before):
        raise ToolError(_WINDOW_RUNS_BACKWARDS)
    asked = _query_string(
        query=query,
        file_type=file_type,
        path=path,
        modified_after=modified_after,
        modified_before=modified_before,
    )
    if not asked:
        raise ToolError(_NOTHING_TO_SEARCH_FOR)

    body = QueryPostRequestBody(
        requests=[
            SearchRequest(
                entity_types=[EntityType.DriveItem],
                query=SearchQuery(query_string=asked),
                from_=offset,
                size=limit,
                aggregations=[
                    AggregationOption(
                        field=_SITE_FIELD,
                        size=MAX_SITES,
                        bucket_definition=BucketAggregationDefinition(
                            sort_by=BucketAggregationSortProperty.Count,
                            is_descending=True,
                            minimum_count=0,
                        ),
                    )
                ],
            )
        ]
    )
    with graph_errors(TOOL_NAME, step=STEP):
        response = await client.search.query.post(body)

    assert response is not None, "Graph answered POST /search/query with no response"
    container = _hits_container(response)
    hits = (container.hits or []) if container is not None else []
    more_to_come = bool(container.more_results_available) if container else False

    return FileSearchResults(
        files=[item for item in (_from_hit(hit) for hit in hits) if item is not None],
        sites=_sites(container),
        next_offset=offset + len(hits) if more_to_come and hits else None,
    )


def _sites(container: SearchHitsContainer | None) -> list[SiteMatches]:
    if container is None:
        return []
    for aggregation in container.aggregations or []:
        if aggregation.field != _SITE_FIELD:
            continue
        return [
            SiteMatches(url=bucket.key, match_count=bucket.count)
            for bucket in aggregation.buckets or []
            if bucket.key is not None and bucket.count is not None
        ]
    return []


def _from_hit(hit: SearchHit) -> DriveItemSummary | None:
    resource = hit.resource
    if not isinstance(resource, DriveItem):
        return None
    return DriveItemSummary.from_item(resource)


def _hits_container(response: QueryPostResponse) -> SearchHitsContainer | None:
    for search_response in response.value or []:
        for container in search_response.hits_containers or []:
            return container
    return None


def _query_string(
    *,
    query: str,
    file_type: str | None,
    path: str | None,
    modified_after: date | datetime | None,
    modified_before: date | datetime | None,
) -> str:
    terms: list[str] = []
    rendered = kql.free_text(query)
    if rendered:
        terms.append(rendered)
    if file_type:
        terms.append(f"filetype:{kql.quoted(file_type)}")
    if path:
        terms.append(f"path:{kql.quoted(path)}")
    if modified_after is not None:
        terms.append(_opening_term(modified_after))
    if modified_before is not None:
        terms.append(_closing_term(modified_before))
    return " AND ".join(terms)


def _opening_term(modified_after: date | datetime) -> str:
    return f"LastModifiedTime>={_wire(opens_at(modified_after))}"


def _closing_term(modified_before: date | datetime) -> str:
    if isinstance(modified_before, datetime):
        return f"LastModifiedTime<={_wire(closes_at(modified_before))}"
    return f"LastModifiedTime<{_wire(opens_at(modified_before + timedelta(days=1)))}"


def _wire(instant: datetime) -> str:
    if instant.microsecond:
        return f"{instant:%Y-%m-%dT%H:%M:%S.%f}Z"
    return f"{instant:%Y-%m-%dT%H:%M:%SZ}"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Search Files",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def search_files(
        query: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Words to find, matched against the file name and the text inside the file. "
                    + "Every word must appear, in any order. Quote words that must sit together, "
                    + '`"budget review"`, to match only that exact phrase. A search operator here '
                    + "is read as plain text, not obeyed."
                ),
            ),
        ],
        file_type: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only files with this extension, written on its own with no dot and no "
                    + "star, for example `docx`, `pdf` or `xlsx`. A folder has no extension, so "
                    + "this also drops every folder from the answer."
                ),
            ),
        ] = None,
        path: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only items under this address: the full web address of a SharePoint site "
                    + "or folder, for example `https://contoso.sharepoint.com/sites/Finance`. "
                    + "Take it from a returned row's `web_url`, or from the user — a bare site "
                    + "or folder name matches nothing here, silently. A site address is the "
                    + "host, then `/sites/` or `/teams/`, then the site name; keep more of the "
                    + "address to scope to one folder instead. A personal OneDrive lives on the "
                    + "`-my` host, and a SharePoint site does not."
                ),
            ),
        ] = None,
        modified_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only items last changed at or after this point. A date, `2026-03-04`, "
                    + "opens at the first instant of that whole UTC day; a moment, "
                    + "`2026-03-04T09:00:00Z`, opens at the exact second named, and a moment "
                    + "with no time zone is read as UTC."
                )
            ),
        ] = None,
        modified_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only items last changed at or before this point, inclusive, in the same "
                    + "two shapes as `modified_after`. A date closes at the end of that whole "
                    + "UTC day, so the same date in both bounds spans exactly that one day; a "
                    + "moment closes at the second named."
                )
            ),
        ] = None,
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "How many results to skip, for paging. Start at 0; pass the previous "
                    + "answer's `next_offset` to reach the next page."
                ),
            ),
        ] = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=(
                    "How many results one page holds. The default is 25 and the most is "
                    + f"{MAX_RESULTS}."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> FileSearchResults:
        return await sharepoint_search_files(
            client,
            query=query,
            file_type=file_type,
            path=path,
            modified_after=modified_after,
            modified_before=modified_before,
            offset=offset,
            limit=limit,
        )
