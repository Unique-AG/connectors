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
Search the files and folders the signed-in user can see in OneDrive and in SharePoint. Use it for \
"find the file about…" and for every question that names a document. `query` is required. The \
other arguments narrow the search, and the tool joins all of them with AND, so each one makes the \
answer smaller. `file_type` keeps one kind of file. `path` keeps one site or one folder. \
`modified_after` and `modified_before` bound the date a file last changed, and each of those two \
days is covered whole, so "the budget file I touched in March" is one call. There is no sort \
here, inside a window or outside one. Microsoft's index returns its own order, so a date window \
does not make an answer "the newest". Each row names a file or a folder and carries no file \
content: pass a row's `uri` to sharepoint_read_file to get the file itself, and to \
sharepoint_browse_folder to list what is in a folder. Every answer also names the sites the \
matches sit on, with a count for each, so a wide search tells you where the answer lives. \
When one site is the right one, search again with that site's address as `path`. \
Use sharepoint_browse_folder instead when \
the user names one folder and wants everything in it, because a search reaches indexed content \
only and a browse reaches every item.\
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
            "The web address of the site. Pass it back as `path` to search this site only. It is "
            + "already in the form `path` wants, so use it word for word."
        )
    )
    match_count: int = Field(
        description=(
            "How many matches sit on this site. This counts every match, not only the ones on "
            + "this page, so it says how much is there before you ask for it."
        )
    )


class FileSearchResults(BaseModel):
    """One page of matches, the sites they sit on, and the offset that reaches the next page."""

    files: list[DriveItemSummary] = Field(
        description=(
            "The files and folders that matched, on this page. Empty means the index matched "
            + "nothing. A search reads indexed content only, so an empty answer is not proof that "
            + "no such file exists. A row that Graph returned no drive for is dropped, because "
            + "this tool cannot address it again."
        )
    )
    sites: list[SiteMatches] = Field(
        description=(
            "The sites the matches sit on, with the most matches first. Microsoft counts these "
            + "across every match, so this says where the answer lives before you page through "
            + "it. Use it to narrow: show the user these sites, then search again with one site's "
            + "`url` as `path`. Empty when every match is in the user's own OneDrive, or when "
            + "Microsoft grouped nothing, which some organisations cause by changing their search "
            + "settings. Empty never means the matches have no site."
        )
    )
    next_offset: int | None = Field(
        description=(
            "The offset that reaches the next page of results, or null when the page cannot "
            + "advance further. Null means either that no more results exist, or that the page "
            + "held no hits to advance past even though Graph said more can exist. In both cases, "
            + "do not ask for this offset again. It counts Graph's hits, not the rows this tool "
            + "returned, because offsets index Graph's own results."
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
                    "Words to find. Microsoft reads the file name and the text inside the file. "
                    + "Every word must appear, in any order. Put double quotes around words that "
                    + 'must sit side by side: `"budget review"` matches only those two words '
                    + "together, and `budget review` matches both words anywhere. This tool "
                    + "searches for a search operator as plain text. It does not obey it. Use the "
                    + "other arguments to filter."
                ),
            ),
        ],
        file_type: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only files of this kind, named by the file extension, for example `docx`, "
                    + "`pdf` or `xlsx`. Write the extension on its own, with no dot and no star. "
                    + "A folder has no extension, so this argument also removes every folder from "
                    + "the answer."
                ),
            ),
        ] = None,
        path: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only items that sit under this address. Give the full web address of a "
                    + "SharePoint site or of a folder, for example "
                    + "`https://contoso.sharepoint.com/sites/Finance`. Take the address from the "
                    + "`web_url` of a row this tool returned, or from the user. A site name or a "
                    + "folder name on its own does not work here. To scope to the whole site that "
                    + "a file sits on, cut its `web_url` after the site name: a SharePoint site "
                    + "address is the host, then `/sites/` or `/teams/`, then the site name, and "
                    + "those two are the only forms SharePoint uses. Keep more of the address to "
                    + "scope to one folder. A space may be written as a space or as `%20`, and a "
                    + "trailing slash makes no difference. The host also separates the two "
                    + "places: a personal OneDrive lives on the `-my` host, and SharePoint sites "
                    + "live on the host without it, so the bare host alone keeps one and drops "
                    + "the other."
                ),
            ),
        ] = None,
        modified_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only items last changed on or after this point, inclusive. Two shapes: a "
                    + "date, `2026-03-04`, which is that whole UTC day from its first instant; or "
                    + "a moment, `2026-03-04T09:00:00Z`, which is the second it names. A moment "
                    + "with no zone is read as UTC, so a user's early morning or late evening can "
                    + "fall on the day beside it. This narrows the search. It does not order the "
                    + "answer, so it is not a way to ask for the newest file."
                )
            ),
        ] = None,
        modified_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only items last changed on or before this point, inclusive, in the same two "
                    + "shapes `modified_after` takes. A date closes at the END of that UTC day, so "
                    + "the whole of it is inside the bound and the same date in both bounds "
                    + "searches that one day. A moment closes at the second it names. Pair it with "
                    + '`modified_after` for a window that has closed, such as "the plan we '
                    + 'changed last week".'
                )
            ),
        ] = None,
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "How many results to skip. Start at 0. Pass the last answer's `next_offset` "
                    + "to reach the next page."
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
