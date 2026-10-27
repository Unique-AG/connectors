"""The routes Kubernetes and Prometheus call, and the metrics of every MCP call."""

import logging
import time
from typing import override

import mcp_types as mt
from fastmcp import FastMCP
from fastmcp.prompts import PromptResult
from fastmcp.resources import ResourceResult
from fastmcp.server.middleware import CallNext
from fastmcp.server.middleware import Middleware as McpMiddleware
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import PlainTextResponse
from starlette.responses import Response

from mcp_observability.metrics import HttpMetricsMiddleware
from mcp_observability.metrics import MetricNamespace
from mcp_observability.metrics import metrics_text

OPS_PATHS = frozenset({"/probe", "/health", "/metrics"})

_log = logging.getLogger("mcp_observability")
_mcp_metrics = MetricNamespace("mcp")
_calls = _mcp_metrics.counter("calls_total", "MCP calls", ["kind", "name", "status"])
_call_duration = _mcp_metrics.histogram(
    "call_duration_seconds", "MCP call duration", ["kind", "name"]
)


def setup_ops(mcp: FastMCP) -> Middleware:
    """Serve `/probe`, `/health` and `/metrics` from `mcp`, count, time and log every tool,
    resource and prompt call, and return the HTTP metrics middleware for the app."""
    mcp.custom_route("/probe", methods=["GET"])(_probe)
    mcp.custom_route("/health", methods=["GET"])(_health)
    mcp.custom_route("/metrics", methods=["GET"])(_metrics)
    mcp.add_middleware(_McpCallMetrics())
    return Middleware(HttpMetricsMiddleware, excluded_paths=OPS_PATHS | {"/", "/favicon.ico"})


async def _probe(_request: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def _health(_request: Request) -> Response:
    return JSONResponse({"status": "healthy"})


async def _metrics(_request: Request) -> Response:
    return PlainTextResponse(metrics_text(), media_type="text/plain; version=0.0.4; charset=utf-8")


class _McpCallMetrics(McpMiddleware):
    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        return await _measured("tool", context.message.name, context, call_next)

    @override
    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: CallNext[mt.ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        return await _measured("resource", str(context.message.uri), context, call_next)

    @override
    async def on_get_prompt(
        self,
        context: MiddlewareContext[mt.GetPromptRequestParams],
        call_next: CallNext[mt.GetPromptRequestParams, PromptResult],
    ) -> PromptResult:
        return await _measured("prompt", context.message.name, context, call_next)


async def _measured[T, R](
    kind: str, name: str, context: MiddlewareContext[T], call_next: CallNext[T, R]
) -> R:
    start = time.perf_counter()
    failure: Exception | None = None
    try:
        return await call_next(context)
    except Exception as error:
        failure = error
        raise
    finally:
        elapsed = time.perf_counter() - start
        status = "ok" if failure is None else type(failure).__name__
        _call_duration.labels(kind=kind, name=name).observe(elapsed)
        _calls.labels(kind=kind, name=name, status=status).inc()
        extra = {
            "kind": kind,
            "operation": name,
            "status": status,
            "duration_ms": round(elapsed * 1000, 2),
        }
        if failure is None:
            _log.info("%s '%s' completed", kind, name, extra=extra)
        else:
            # FastMCP logs an unexpected error with its traceback already, and reaches here with
            # it wrapped in a ToolError, so this line adds only the outcome.
            _log.warning("%s '%s' failed: %s", kind, name, failure, extra=extra)
