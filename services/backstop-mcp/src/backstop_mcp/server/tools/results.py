"""MCP wire-shape helpers for tool returns.

Tools keep domain Pydantic models internally and wrap them here so the MCP surface matches
the Unique FastMCP pattern (`CallToolResult` + `TextContent`).
"""

from __future__ import annotations

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel


def tool_result(payload: BaseModel) -> CallToolResult:
    """Serialize a domain payload as a single JSON text content block.

    Uses Python field names (`by_alias=False`) so tool JSON matches the pydantic models the
    server types against, not Backstop's camelCase wire aliases.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=payload.model_dump_json(by_alias=False))]
    )


def tool_error(message: str) -> CallToolResult:
    return CallToolResult(isError=True, content=[TextContent(type="text", text=message)])
