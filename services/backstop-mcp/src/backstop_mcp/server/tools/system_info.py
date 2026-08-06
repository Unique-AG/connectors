from fastmcp.tools import tool
from mcp.types import CallToolResult, ToolAnnotations

from backstop_mcp.server.runtime import get_backstop_client
from backstop_mcp.server.tools.results import tool_result


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def get_system_info() -> CallToolResult:
    """Fetch Backstop's system info for the currently connected user.

    An example tool showing the full authenticated-call path end to end: FastMCP has
    already validated the caller's MCP access token; `get_backstop_client` resolves *their*
    stored Backstop credential (not a shared service account) and builds a `BackstopClient`
    authenticated as them. That client auto-raises on any error response (a revoked credential
    surfaces as `BackstopAuthError`; anything else as `BackstopApiError`/
    `BackstopRateLimitError`), so this tool doesn't need to check status codes itself.
    """
    client = await get_backstop_client()
    payload = await client.get("/system-info")
    assert isinstance(payload, dict), "Backstop /system-info returns a JSON object"
    return tool_result(payload)
