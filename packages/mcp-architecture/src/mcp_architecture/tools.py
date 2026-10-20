"""The tools an MCP serves, as a client lists them: their descriptions and their snapshot."""

import json
from typing import cast

from fastmcp import Client, FastMCP
from mcp_types import Tool

# mcp-openapi's `PASSTHROUGH_TAG`, which `upstream_tools` in an OpenAPI MCP sets. Such a tool says
# what the spec says until promoted. A copy, since an MCP without an OpenAPI upstream has no
# mcp-openapi to import it from.
PASSTHROUGH_TAG = "passthrough"


async def undescribed_tools(server: FastMCP) -> list[str]:
    """Each tool without a description and each parameter without one, as `tool(parameter)`.

    The descriptions are all the model reads before it picks a tool and fills its arguments.
    """
    tools = [tool for tool in await _list_tools(server) if PASSTHROUGH_TAG not in _tags(tool)]
    return [tool.name for tool in tools if not tool.description] + [
        f"{tool.name}({parameter})"
        for tool in tools
        for parameter, schema in cast(
            dict[str, dict[str, object]], tool.input_schema.get("properties", {})
        ).items()
        if not schema.get("description")
    ]


async def tool_surface(server: FastMCP) -> str:
    """The tools the server lists, sorted by name, as JSON to snapshot with `file_regression`.

    Of `_meta`, only the tags are kept: they decide whether `undescribed_tools` checks a tool.
    """
    surface = [
        {
            **tool.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"meta"}),
            **({"_meta": {"fastmcp": {"tags": sorted(tags)}}} if (tags := _tags(tool)) else {}),
        }
        for tool in sorted(await _list_tools(server), key=lambda tool: tool.name)
    ]
    return json.dumps(surface, indent=2, sort_keys=True) + "\n"


async def _list_tools(server: FastMCP) -> list[Tool]:
    async with Client(server) as client:
        return await client.list_tools()


def _tags(tool: Tool) -> list[str]:
    fastmcp = cast(dict[str, object], (tool.meta or {}).get("fastmcp", {}))
    return cast(list[str], fastmcp.get("tags", []))
