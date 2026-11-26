import typing
from datetime import date, datetime
from typing import cast

import httpx
from fastmcp import FastMCP
from fastmcp.tools import FunctionTool
from pydantic import TypeAdapter

from office_365_mcp.tools import TOOL_NAMES, register_tools, resolve

_MIDNIGHT_WITH_AN_OFFSET = "2026-11-23T00:00:00+14:00"


def _names(hint: object, kind: type) -> bool:
    arguments: tuple[object, ...] = typing.get_args(hint)
    return hint is kind or any(_names(argument, kind) for argument in arguments)


async def _day_or_moment_parameters() -> dict[str, object]:
    server = FastMCP[None](name="every-tool")
    async with httpx.AsyncClient() as transport:
        register_tools(server, transport, resolve(presets=None, enabled=list(TOOL_NAMES)))
        tools = await server.list_tools()
    found: dict[str, object] = {}
    for tool in tools:
        assert isinstance(tool, FunctionTool)
        hints: dict[str, object] = typing.get_type_hints(tool.fn, include_extras=True)
        for name, hint in hints.items():
            if name != "return" and _names(hint, date) and _names(hint, datetime):
                found[f"{tool.name}.{name}"] = hint
    return found


async def test_every_date_bound_keeps_the_instant_of_a_midnight_moment() -> None:
    parameters = await _day_or_moment_parameters()

    lost = [
        name
        for name, hint in parameters.items()
        if not isinstance(
            TypeAdapter[object](cast("type[object]", hint)).validate_python(
                _MIDNIGHT_WITH_AN_OFFSET
            ),
            datetime,
        )
    ]

    assert "outlook_list_mail.received_after" in parameters
    assert lost == []
