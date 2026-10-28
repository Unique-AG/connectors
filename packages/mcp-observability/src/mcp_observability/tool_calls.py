"""One line when a tool call starts and one when it ends, with what `@trace_arguments` declared."""

import asyncio
import logging
import time
from typing import override

import mcp_types as mt
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult

from mcp_observability.failures import failure_level
from mcp_observability.logging import add_filter_once
from mcp_observability.trace_declarations import tool_call_record

_log = logging.getLogger("mcp_observability.tool_calls")
_MAX_TOOL_NAME = 64


class ToolCallObservabilityMiddleware(Middleware):
    """Logs one `started` and one `completed`, `failed` or `cancelled` line per tool call, a failure
    at its `failure_level`. Make it the outermost FastMCP middleware: it drops FastMCP's own
    per-call lines, which repeat these and can quote the input."""

    def __init__(self) -> None:
        super().__init__()
        add_filter_once("fastmcp.server.server", _FastMcpToolCallLines)
        add_filter_once("mcp_observability", _OpsToolCallLines)

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool = context.message.name[:_MAX_TOOL_NAME]
        base: dict[str, object] = {
            "tool": tool,
            "argument_names": sorted((context.message.arguments or {}).keys()),
            "subject": _subject(),
        }
        started = time.monotonic()
        with tool_call_record() as declared:
            _log.info("Tool call started", extra=base)
            try:
                result = await call_next(context)
            except asyncio.CancelledError:
                _log.info(
                    "Tool call cancelled",
                    extra={**base, **declared, "duration_ms": _ms(started)},
                )
                raise
            except Exception as error:
                _log.log(
                    failure_level(error),
                    "Tool call failed",
                    exc_info=error,
                    extra={**base, **declared, "duration_ms": _ms(started)},
                )
                raise
            _log.info(
                "Tool call completed", extra={**base, **declared, "duration_ms": _ms(started)}
            )
            return result


class _FastMcpToolCallLines(logging.Filter):
    @override
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.msg
        return not (
            isinstance(message, str)
            and message.startswith(("Error calling tool", "Invalid arguments for tool"))
        )


class _OpsToolCallLines(logging.Filter):
    @override
    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "kind", None) != "tool" or not hasattr(record, "duration_ms")


def _subject() -> str | None:
    """Our internal user id. Absent outside a request."""
    try:
        token = get_access_token()
    except RuntimeError:
        return None
    return token.subject if token is not None else None


def _ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 1)
