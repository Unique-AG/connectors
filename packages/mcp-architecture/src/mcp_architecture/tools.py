"""The tools an MCP serves, as a client lists them: their descriptions, their schemas, their
snapshot and what an error inside one shows."""

import json
import logging
from collections.abc import Callable, Generator
from contextlib import AbstractAsyncContextManager, contextmanager
from typing import cast

from fastmcp import Client, FastMCP
from fastmcp.server.providers.openapi import OpenAPITool
from fastmcp.tools import Tool as ServedTool
from mcp_types import TextContent, Tool

type ServerFactory = Callable[[], AbstractAsyncContextManager[FastMCP]]

# Some clients reject a tool whose input schema is not a plain object at its root.
_ROOT_COMBINATORS = ["anyOf", "oneOf", "allOf", "not"]
_PROBE_TOOL = "mcp_architecture_masking_probe"
_PROBE_SECRET = "mcp-architecture-probe-secret"


async def undescribed_tools(server: FastMCP) -> list[str]:
    """Each tool without a description and each parameter without one, as `tool(parameter)`.

    The descriptions are all the model reads before it picks a tool and fills its arguments. A
    tool served straight from an OpenAPI spec says what the spec says, so it is skipped.
    """
    tools = [tool for tool in await server.list_tools() if not isinstance(tool, OpenAPITool)]
    return [tool.name for tool in tools if not tool.description] + [
        f"{tool.name}({parameter})"
        for tool in tools
        for parameter, schema in cast(
            dict[str, dict[str, object]], tool.parameters.get("properties", {})
        ).items()
        if not schema.get("description")
    ]


async def tools_with_a_root_combinator(server: FastMCP) -> list[str]:
    """Each tool whose input schema combines schemas at its root, as `tool: keyword`. Tools served
    from a spec are checked too, since a client rejects them alike."""
    return [
        f"{tool.name}: {keyword}"
        for tool in await _list_tools(server)
        for keyword in _ROOT_COMBINATORS
        if keyword in tool.input_schema
    ]


async def masks_error_details(factory: ServerFactory) -> bool:
    """Whether an unexpected error inside a tool reaches the client without its message, which can
    carry a secret, an internal URL or the upstream's own words.

    Adds a tool that raises to a server `factory` builds for this check alone, and calls it. A
    call that never reaches the tool, such as one a middleware rejects, proves nothing, so it
    counts as unmasked.
    """
    calls: list[None] = []

    def raise_probe_secret() -> None:
        calls.append(None)
        raise RuntimeError(_PROBE_SECRET)

    async with factory() as server:
        server.add_tool(ServedTool.from_function(raise_probe_secret, name=_PROBE_TOOL))
        async with Client(server) as client:
            with _fastmcp_logs_off():
                result = await client.call_tool(_PROBE_TOOL, {}, raise_on_error=False)
    return (
        bool(calls)
        and result.is_error
        and not any(
            _PROBE_SECRET in block.text
            for block in result.content
            if isinstance(block, TextContent)
        )
    )


@contextmanager
def _fastmcp_logs_off() -> Generator[None]:
    """FastMCP logs the probe's error with its traceback, which reads as a failure of the check."""
    logger = logging.getLogger("fastmcp")
    level = logger.level
    logger.setLevel(logging.CRITICAL + 1)
    try:
        yield
    finally:
        logger.setLevel(level)


async def tool_surface(server: FastMCP) -> str:
    """The tools the server lists, sorted by name, as JSON for `poe architecture` to compare
    with `tests/tool_surface.generated.json`.

    Of `_meta`, only the tags are kept.
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
