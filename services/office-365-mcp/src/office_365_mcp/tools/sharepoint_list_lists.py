from collections.abc import Mapping
from typing import Annotated, Self
from urllib.parse import quote, unquote, urlsplit

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.method import Method
from msgraph.generated.models.list_ import List_
from msgraph.generated.models.site import Site
from msgraph.generated.sites.item.lists.lists_request_builder import ListsRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    collect_pages,
    graph_errors,
    graph_step,
    request_with_query,
    send_parsed,
)
from office_365_mcp.shared.handles import ListHandle
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "sharepoint_list_lists"

STEP_SITE = "site_by_url"
STEP_LISTS = "site_lists"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Sites.Read.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"site": "https://contoso.sharepoint.com/sites/Finance"}

_LIST_FIELDS: tuple[str, ...] = ("id", "name", "displayName", "description", "webUrl", "list")

# Reserved expansion keeps the `:` and `/` of `{host}:{path}`, which Graph needs unescaped.
_SITE_BY_PATH = "{+baseurl}/sites/{+site_path}"

_LIBRARY_TEMPLATES = frozenset({"documentLibrary", "mySiteDocumentLibrary"})

_ListsQuery = ListsRequestBuilder.ListsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the SharePoint lists of one site, each with a handle. Pass `uri` as `list` to \
sharepoint_get_list to see its columns, or to sharepoint_list_items to read its items.

Notes:
- Hidden lists and document libraries are left out. If this deployment exposes \
sharepoint_search_files, use it to find files.
- This tool does not sort the rows.
"""

_NOT_A_SITE = (
    f"{TOOL_NAME} takes the web address of a site, such as the `web_url` of a row from "
    + "sharepoint_search_sites. It starts with https://. A site name is not one, nor is a list "
    + "handle. If you call this tool again with the same arguments, the call will fail the same "
    + "way."
)


class ListSummary(BaseModel):
    uri: str = Field(
        description=(
            "The handle of this list. Pass it as `list` to sharepoint_get_list or "
            + "sharepoint_list_items. Copy it exactly. Never build one."
        )
    )
    display_name: str | None = Field(
        description=(
            "The title of the list. Titles can repeat, so use `uri` to tell two lists apart. "
            + "Null when Graph recorded none."
        )
    )
    description: str | None = Field(
        description="The description of the list. Null when the list has none."
    )
    web_url: str | None = Field(
        description=(
            "The address that opens the list in a browser. Give it to the user when you answer "
            + "about this list. It is not a handle. Null when Graph recorded none."
        )
    )

    @classmethod
    def from_list(cls, site_id: str, found: List_) -> Self:
        assert found.id is not None, "a list without an id reached the row builder"
        return cls(
            uri=ListHandle(site_id, found.id).uri,
            display_name=found.display_name or found.name,
            description=found.description or None,
            web_url=found.web_url,
        )


class SiteLists(BaseModel):
    lists: list[ListSummary] = Field(
        description=(
            "The visible lists of the site, in the order Microsoft returned them. An empty list "
            + "means that the site has no list besides document libraries and hidden lists."
        )
    )
    capped: bool = Field(
        description=(
            "True when `limit` or the cap of 1000 lists stopped the listing while more lists "
            + "remained. Raise `limit` to get more. False when the listing ended on its own."
        )
    )


async def list_lists(client: GraphServiceClient, *, site: str, limit: int) -> SiteLists:
    assert limit >= 1, f"limit must be at least 1, got {limit}"
    site_path = _site_path(site)

    with graph_errors(TOOL_NAME):
        with graph_step(STEP_SITE):
            resolved = await _site(client, site_path)
        assert resolved is not None and resolved.id is not None, "Graph returned a site with no id"
        site_id = resolved.id
        with graph_step(STEP_LISTS):
            first_page = await client.sites.by_site_id(site_id).lists.get(
                request_configuration=RequestConfiguration[_ListsQuery](
                    query_parameters=_ListsQuery(select=list(_LIST_FIELDS))
                )
            )
            assert first_page is not None, "Graph answered a list listing with no collection"
            collected = await collect_pages(first_page, client, limit=limit, matches=_is_shown)

    return SiteLists(
        lists=[ListSummary.from_list(site_id, found) for found in collected.items],
        capped=collected.capped,
    )


async def _site(client: GraphServiceClient, site_path: str) -> Site | None:
    request = request_with_query(
        Method.GET,
        _SITE_BY_PATH,
        {**client.sites.path_parameters, "site_path": site_path},
        query={},
    )
    request.headers.try_add("Accept", "application/json")
    return await send_parsed(client, request, Site)


def _is_shown(found: List_) -> bool:
    info = found.list_
    hidden = info is not None and bool(info.hidden)
    library = info is not None and info.template in _LIBRARY_TEMPLATES
    return found.id is not None and not hidden and not library


def _site_path(site: str) -> str:
    """`{host}` or `{host}:{path}`, the two ways Graph addresses a site by its web address."""
    parts = urlsplit(site)
    decoded = parts.path
    while (again := unquote(decoded)) != decoded:
        decoded = again
    segments = decoded.replace("\\", "/").strip("/").split("/")
    if parts.scheme not in {"http", "https"} or not parts.hostname or {".", ".."} & {*segments}:
        raise ToolError(_NOT_A_SITE)
    path = quote(parts.path.rstrip("/"), safe="/%")
    return f"{parts.hostname}:{path}" if path else parts.hostname


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Lists",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def sharepoint_list_lists(
        site: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The web address of the site, such as "
                    + "`https://contoso.sharepoint.com/sites/Finance`. Take the `web_url` of a row "
                    + "from sharepoint_search_sites."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "How many lists to return, at most. The field `capped` says if the listing "
                    + "stopped early. The default value is 25."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> SiteLists:
        return await list_lists(client, site=site, limit=limit)
