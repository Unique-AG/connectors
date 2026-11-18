from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from mcp_types import TextContent
from pydantic import BaseModel

type McpClient = Client[FastMCPTransport]


async def call_tool[M: BaseModel](
    client: McpClient, tool: str, arguments: dict[str, object], *, returns: type[M]
) -> M:
    """The tool's structured result, parsed into the context model it returns."""
    result = await client.call_tool(tool, arguments)
    return returns.model_validate(result.structured_content)


async def tool_error(client: McpClient, tool: str, arguments: dict[str, object]) -> str:
    """The text of the error the call must fail with."""
    result = await client.call_tool(tool, arguments, raise_on_error=False)
    assert result.is_error, f"{tool} succeeded with {arguments}"
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))
