from backstop_mcp.backstop_client import GetRequest, get_backstop_client


async def get_system_info() -> dict[str, object]:
    """Fetch Backstop's system info for the currently connected user.

    An example tool showing the full authenticated-call path end to end: FastMCP has
    already validated the caller's MCP access token; `get_backstop_client` resolves *their*
    stored Backstop credential via `auth/context.py` (not a shared service account) and
    builds a `BackstopClient` authenticated as them. That client auto-raises on any error
    response (a revoked credential surfaces as `BackstopAuthError`; anything else as
    `BackstopApiError`/`BackstopRateLimitError`), so this tool doesn't need to check status
    codes itself.
    """
    async with await get_backstop_client() as client:
        return await client.get(GetRequest(path="/system-info"))
