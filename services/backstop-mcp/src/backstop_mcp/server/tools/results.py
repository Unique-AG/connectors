"""MCP wire-shape helpers for tool returns.

Tools keep domain Pydantic models internally and wrap them here so the MCP surface matches
the Unique FastMCP pattern (`CallToolResult` + `TextContent`).
"""

from __future__ import annotations

import json

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel


def tool_result(payload: BaseModel | dict[str, object]) -> CallToolResult:
    """Serialize a domain payload as a single JSON text content block."""
    if isinstance(payload, BaseModel):
        text = payload.model_dump_json()
    else:
        text = json.dumps(payload)
    return CallToolResult(content=[TextContent(type="text", text=text)])


def tool_error(message: str) -> CallToolResult:
    return CallToolResult(isError=True, content=[TextContent(type="text", text=message)])
