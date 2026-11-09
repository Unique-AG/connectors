import re
from urllib.parse import quote, unquote, urlsplit

from fastmcp.exceptions import ToolError
from kiota_abstractions.method import Method
from msgraph.generated.models.site import Site
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import request_with_query, send_parsed

# Reserved expansion keeps the `:` and `/` of `{host}:{path}`, which Graph needs unescaped.
_SITE_BY_PATH = "{+baseurl}/sites/{+site_path}"

_DNS_NAME = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]", re.IGNORECASE
)


def site_path_of(site: str, tool: str) -> str:
    """`{host}` or `{host}:{path}`, the two ways Graph addresses a site by its web address."""
    parts = urlsplit(site)
    decoded = parts.path
    while (again := unquote(decoded)) != decoded:
        decoded = again
    segments = decoded.replace("\\", "/").strip("/").split("/")
    host = parts.hostname or ""
    plain_host = parts.netloc.lower() == host and _DNS_NAME.fullmatch(host) is not None
    encoded_separator = re.search(r"%(?:2f|5c)", site, re.IGNORECASE) is not None
    if (
        parts.scheme not in {"http", "https"}
        or not plain_host
        or encoded_separator
        or {".", ".."} & {*segments}
    ):
        raise ToolError(_not_a_site(tool))
    path = quote(parts.path.rstrip("/"), safe="/%")
    return f"{host}:{path}" if path else host


def _not_a_site(tool: str) -> str:
    return (
        f"{tool} takes the web address of a site, such as the `web_url` of a row from "
        + "sharepoint_search_sites. It starts with https://. A site name is not one, nor is a "
        + "list handle. If you call this tool again with the same arguments, the call will fail "
        + "the same way."
    )


async def site_by_path(client: GraphServiceClient, site_path: str) -> Site | None:
    request = request_with_query(
        Method.GET,
        _SITE_BY_PATH,
        {**client.sites.path_parameters, "site_path": site_path},
        query={},
    )
    request.headers.try_add("Accept", "application/json")
    return await send_parsed(client, request, Site)
