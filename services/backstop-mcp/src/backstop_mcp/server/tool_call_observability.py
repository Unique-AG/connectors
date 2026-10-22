"""One INFO line when a tool call starts and one when it ends, on FastMCP's tool-call span."""

import asyncio
import logging
import time
from typing import override

import pydantic
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams
from opentelemetry import trace

from backstop_mcp.observability import failure_event, info_event, span_attributes, tool_call_scope

logger = logging.getLogger(__name__)

_MAX_TOOL_NAME = 64


class ToolCallObservabilityMiddleware(Middleware):
    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool = context.message.name[:_MAX_TOOL_NAME]
        base = {
            "tool": tool,
            "argument_names": sorted((context.message.arguments or {}).keys()),
            "subject": _subject(),
        }
        started = time.monotonic()
        with tool_call_scope() as call:
            # The current span is FastMCP's `tools/call <tool>` span (opened before middleware
            # on the HTTP seam). In-process calls open that span inside `call_next` instead.
            trace.get_current_span().set_attributes(span_attributes(base))
            info_event(logger, "tool.call.start", **base)
            try:
                result = await call_next(context)
            except asyncio.CancelledError:
                info_event(
                    logger,
                    "tool.call.cancelled",
                    **base,
                    duration_ms=_ms(started),
                )
                raise
            except Exception as exc:
                failure_event(
                    logger,
                    "tool.call.failed",
                    exc,
                    **{
                        **base,
                        **call.fields,
                        "duration_ms": _ms(started),
                        "invalid_arguments": _invalid_argument_locations(exc),
                    },
                )
                raise
            info_event(
                logger,
                "tool.call.completed",
                **{**base, **call.fields, "duration_ms": _ms(started)},
            )
            return result


def _subject() -> str | None:
    """Our internal user id. Absent outside a request."""
    try:
        token = get_access_token()
    except RuntimeError:
        return None
    if token is None:
        return None
    return token.subject


def _invalid_argument_locations(exc: BaseException) -> list[str] | None:
    """Field paths from a pydantic argument error. Locations only, never input values."""
    cause = exc.__cause__
    if not isinstance(cause, pydantic.ValidationError):
        return None
    return sorted(
        {
            ".".join(str(part) for part in error["loc"])
            for error in cause.errors(include_input=False)
        }
    )


def _ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 1)
