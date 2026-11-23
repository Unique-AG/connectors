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
    """Each tool without a description, each argument without one as `tool(argument)`, and each
    field of its output without one as `tool -> field`.

    The descriptions are all the model reads before it picks a tool, fills its arguments and reads
    what it returns. A field is named by its path, `place_order(order.sku)` or
    `get_case -> group.id`, and a field of a model FastMCP keeps in `$defs`, a recursive one, by
    the model, `list_groups -> Group.id`. A field that holds one model, or none, is described by
    that model's docstring. A tool served straight from an OpenAPI spec says what the spec says,
    so it is skipped.
    """
    tools = [tool for tool in await server.list_tools() if not isinstance(tool, OpenAPITool)]
    return [
        *(tool.name for tool in tools if not tool.description),
        *(
            f"{tool.name}({field})"
            for tool in tools
            for field in _undescribed_fields(tool.parameters)
        ),
        *(
            f"{tool.name} -> {field}"
            for tool in tools
            if tool.output_schema
            for field in _undescribed_fields(tool.output_schema)
        ),
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
            with _probe_logs_off():
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
def _probe_logs_off() -> Generator[None]:
    """FastMCP and the tool-call middleware log the probe's error with its traceback, which reads
    as a failure of the check."""
    loggers = [logging.getLogger(name) for name in ("fastmcp", "mcp_observability")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.CRITICAL + 1)
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels, strict=True):
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


type _Schema = dict[str, object]


def _undescribed_fields(root: _Schema) -> list[str]:
    """Each field of `root` and of the models in its `$defs` without a description, each model's
    fields named once, after the model."""
    defs = cast(dict[str, _Schema], root.get("$defs", {}))
    properties = cast(dict[str, _Schema], root.get("properties", {}))
    # FastMCP wraps a result that is not an object as `result`, which the tool's description says.
    wrapped = root.get("x-fastmcp-wrap-result") is True
    return [
        *(
            _undescribed_within(properties["result"], defs=defs, path="result")
            if wrapped
            else _undescribed_within(root, defs=defs, path="")
        ),
        *(
            field
            for name, model in sorted(defs.items())
            for field in _undescribed_within(model, defs=defs, path=name)
        ),
    ]


def _undescribed_within(schema: _Schema, *, defs: dict[str, _Schema], path: str) -> list[str]:
    """The fields under `schema` without a description, up to a `$ref`, which `_undescribed_fields`
    walks on its own."""
    found: list[str] = []
    for name, field in cast(dict[str, _Schema], schema.get("properties", {})).items():
        field_path = f"{path}.{name}" if path else name
        if not _is_described(field, defs=defs):
            found.append(field_path)
        found.extend(_undescribed_within(field, defs=defs, path=field_path))
    for key in ("items", "additionalProperties"):
        if isinstance(inner := schema.get(key), dict):
            found.extend(_undescribed_within(cast(_Schema, inner), defs=defs, path=f"{path}[]"))
    for key in ("anyOf", "oneOf", "allOf"):
        for member in cast(list[_Schema], schema.get(key, [])):
            found.extend(_undescribed_within(member, defs=defs, path=path))
    return found


def _is_described(field: _Schema, *, defs: dict[str, _Schema]) -> bool:
    """By its own description, or by the docstring of the one model it holds, optional or not."""
    if field.get("description"):
        return True
    if isinstance(ref := field.get("$ref"), str):
        return bool(defs.get(ref.removeprefix("#/$defs/"), {}).get("description"))
    members = [
        member
        for member in cast(list[_Schema], field.get("anyOf", []))
        if member.get("type") != "null"
    ]
    return len(members) == 1 and _is_described(members[0], defs=defs)
