from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp.exceptions import ToolError
import httpx2
from mcp_runtime import RetryingTransport

from mcp_skeleton.upstream.settings import UpstreamSettings

# The name the contexts and tools import the client by, kept the same in every MCP whatever
# the client is. It is an alias, not an abstraction: its API is the client's own.
Upstream = httpx2.AsyncClient


class UpstreamError(ToolError):
    """The upstream answered with an error status. A ToolError, so it reaches the MCP client."""


async def _raise_for_status(response: httpx2.Response) -> None:
    if response.is_success:
        return
    await response.aread()
    request = response.request
    url = request.url.copy_with(query=None)
    message = f"{response.status_code} {response.reason_phrase} for {request.method} {url}"
    body = response.text[:200]
    raise UpstreamError(f"{message}: {body}" if body else message)


@asynccontextmanager
async def open_upstream(
    settings: UpstreamSettings, transport: httpx2.AsyncBaseTransport | None = None
) -> AsyncGenerator[Upstream]:
    async with httpx2.AsyncClient(
        base_url=str(settings.api_url).rstrip("/"),
        timeout=settings.timeout_seconds,
        transport=RetryingTransport(transport or httpx2.AsyncHTTPTransport(), settings.retry),
        headers={
            "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
            "Accept": "application/json",
        },
        event_hooks={"response": [_raise_for_status]},
    ) as http:
        yield http
