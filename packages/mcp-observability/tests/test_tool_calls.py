import asyncio
import io
import json
import logging
from collections.abc import AsyncIterator
from collections.abc import Iterator
from typing import cast

import mcp_types as mt
import pytest
from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from mcp_configs import LoggingSettings

from mcp_observability import PinoJsonFormatter
from mcp_observability import ToolCallObservabilityMiddleware
from mcp_observability import configure_logging
from mcp_observability import metrics_text
from mcp_observability import setup_ops
from mcp_observability import trace_arguments

_CANARY = "zq-canary-value"


@pytest.fixture
def pino() -> Iterator[io.StringIO]:
    """What the output handler writes, read back line by line."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    root.handlers = []
    configure_logging(LoggingSettings(), own_loggers=("tests",))
    written = io.StringIO()
    (output,) = [
        cast("logging.StreamHandler[io.TextIOBase]", handler)
        for handler in root.handlers
        if isinstance(handler.formatter, PinoJsonFormatter)
    ]
    output.setStream(written)
    yield written
    root.handlers, root.level = handlers, level


@pytest.fixture
async def client() -> AsyncIterator[Client[FastMCPTransport]]:
    server = FastMCP("kiosk", middleware=[ToolCallObservabilityMiddleware()])
    setup_ops(server)

    @server.tool
    @trace_arguments("till", result=lambda sold: {"sold": sold})
    async def sell(till: int, note: str) -> int:
        del note
        return till * 2

    @server.tool
    async def missing() -> str:
        raise ToolError(f"No till named {_CANARY}")

    @server.tool
    async def crash() -> str:
        raise KeyError(_CANARY)

    async with Client(server) as connected:
        yield connected


def _lines(pino: io.StringIO) -> list[dict[str, object]]:
    lines = [json.loads(line) for line in pino.getvalue().splitlines()]
    assert _CANARY not in json.dumps(lines)
    return lines


def _tool_lines(pino: io.StringIO) -> list[dict[str, object]]:
    return [line for line in _lines(pino) if str(line["msg"]).startswith("Tool call")]


async def test_a_call_logs_started_and_completed_with_the_declared_values_only(
    client: Client[FastMCPTransport], pino: io.StringIO
) -> None:
    await client.call_tool("sell", {"till": 3, "note": _CANARY})

    started, completed = _tool_lines(pino)
    assert started["msg"] == "Tool call started"
    assert started["tool"] == "sell"
    assert started["argument_names"] == ["note", "till"]
    assert completed["msg"] == "Tool call completed"
    assert completed["log_level"] == "info"
    assert completed["till"] == 3
    assert completed["sold"] == 6
    assert isinstance(completed["duration_ms"], float)


async def test_a_tool_error_is_a_warning_naming_the_error_without_its_text(
    client: Client[FastMCPTransport], pino: io.StringIO
) -> None:
    await client.call_tool("missing", {}, raise_on_error=False)

    _, failed = _tool_lines(pino)
    assert failed["msg"] == "Tool call failed"
    assert failed["log_level"] == "warn"
    assert failed["error_type"] == "ToolError"
    assert "err" not in failed


async def test_a_bug_is_an_error_with_frames_and_types_but_no_message(
    client: Client[FastMCPTransport], pino: io.StringIO
) -> None:
    await client.call_tool("crash", {}, raise_on_error=False)

    _, failed = _tool_lines(pino)
    assert failed["log_level"] == "error"
    err = cast("dict[str, str]", failed["err"])
    assert "KeyError" in err["stack"]
    assert "message" not in err


async def test_an_invalid_argument_is_named_but_not_quoted(
    client: Client[FastMCPTransport], pino: io.StringIO
) -> None:
    await client.call_tool("sell", {"till": _CANARY, "note": "x"}, raise_on_error=False)

    _, failed = _tool_lines(pino)
    assert failed["log_level"] == "warn"
    assert failed["failed_fields"] == ["till (int_parsing, got str)"]


async def test_the_duplicate_per_call_lines_are_dropped_and_the_metrics_kept(
    client: Client[FastMCPTransport], pino: io.StringIO
) -> None:
    await client.call_tool("crash", {}, raise_on_error=False)
    await client.call_tool("sell", {"till": "x", "note": "x"}, raise_on_error=False)

    messages = [str(line["msg"]) for line in _lines(pino)]
    assert not [message for message in messages if not message.startswith("Tool call")]
    assert 'mcp_calls_total{kind="tool",name="crash",status="ToolError"}' in (
        metrics_text().decode()
    )


async def test_a_cancelled_call_is_logged_as_cancelled(
    pino: io.StringIO,
) -> None:
    middleware = ToolCallObservabilityMiddleware()
    context = MiddlewareContext(message=mt.CallToolRequestParams(name="sell", arguments={}))

    async def cancelled(context: MiddlewareContext[mt.CallToolRequestParams]) -> ToolResult:
        del context
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await middleware.on_call_tool(context, cancelled)

    _, ended = _tool_lines(pino)
    assert ended["msg"] == "Tool call cancelled"
    assert ended["log_level"] == "info"
