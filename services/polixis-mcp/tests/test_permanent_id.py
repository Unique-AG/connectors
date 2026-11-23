from tests.polixis_responses import DISSOLVED_PID
from tests.tool_calls import McpClient
from tests.tool_calls import tool_error


async def test_a_dissolved_pid_reaches_the_client_with_its_former_members(
    mcp_client: McpClient,
) -> None:
    error = await tool_error(mcp_client, "resolve_permanent_id", {"pid": DISSOLVED_PID})

    assert error.startswith("HTTP error 410")
    assert "O00000000000000000000000000000100" in error
    assert "O00000000000000000000000000000101" in error
