from collections.abc import Mapping
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from kiota_abstractions.method import Method
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.generated.models.site import Site
from msgraph.generated.models.site_collection_response import SiteCollectionResponse
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, request_with_query
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "sharepoint_search_sites"

STEP = "site_search"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Sites.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"query": "finance"}

_DESCRIPTION = """\
Finds SharePoint sites by free text, for the signed-in user. Each row has the `web_url` of one \
site, with its `display_name` and its `description`. Pass `web_url` as `path` to \
sharepoint_search_files to search only this site. This tool finds sites. It does not find files \
or folders.

Notes:
- Microsoft Graph matches `query` against several properties of a site, not only its title. \
This tool keeps the order that Graph gives and does not sort the rows.
"""


class SiteSummary(BaseModel):
    web_url: str = Field(
        description=(
            "The web address of the site, for example "
            + "`https://contoso.sharepoint.com/sites/Finance`. Pass it as `path` to "
            + "sharepoint_search_files to search only this site. Give it to the user when they "
            + "ask where the site is."
        )
    )
    display_name: str | None = Field(
        description=(
            "The title of the site, as Graph reports it. Titles can repeat, so use `web_url` to "
            + "tell two sites apart. Null when Graph recorded none."
        )
    )
    description: str | None = Field(
        description=(
            "The descriptive text that the owner gave the site. Null when the site has no "
            + "description, or when Graph recorded none."
        )
    )

    @classmethod
    def from_site(cls, site: Site) -> Self | None:
        if site.web_url is None:
            return None
        return cls(
            web_url=site.web_url,
            display_name=site.display_name or site.name,
            description=site.description or None,
        )


class SiteList(BaseModel):
    sites: list[SiteSummary] = Field(
        description=(
            "The sites that matched, in the order Microsoft returned them. An empty list means "
            + "that no site matched. This tool leaves out a site that Graph reports with no web "
            + "address, because a row without one cannot be passed as `path`."
        )
    )
    capped: bool = Field(
        description=(
            "True when `limit` or the cap of 1000 sites stopped this search while more sites "
            + "matched. To get more sites, raise `limit` up to 1000, or make `query` more "
            + "specific. False when the search ended on its own."
        )
    )


async def search_sites(client: GraphServiceClient, *, query: str, limit: int) -> SiteList:
    assert limit >= 1, f"limit must be at least 1, got {limit}"
    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await _first_page(client, query)
        assert first_page is not None, "Graph answered a site search with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return SiteList(
        sites=[row for site in collected.items if (row := SiteSummary.from_site(site)) is not None],
        capped=collected.capped,
    )


async def _first_page(client: GraphServiceClient, query: str) -> SiteCollectionResponse | None:
    sites = client.sites
    request = request_with_query(
        Method.GET,
        sites.url_template,
        sites.path_parameters,
        query={"search": query},
    )
    request.headers.try_add("Accept", "application/json")
    return await client.request_adapter.send_async(  # pyright: ignore[reportUnknownMemberType]
        request, SiteCollectionResponse, {"XXX": ODataError}
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Search Sites",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def sharepoint_search_sites(
        query: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Free text to look for. Microsoft Graph matches it against several "
                    + "properties of a site, not only the title. Use a word from the name that "
                    + "the user gave."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "How many sites to return, at most. The field `capped` says if the search "
                    + "stopped early. The default value is 25."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> SiteList:
        return await search_sites(client, query=query, limit=limit)
