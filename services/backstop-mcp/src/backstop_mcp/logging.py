"""Logging setup via `unique_mcp.logging` (pino-json on stderr)."""

import logging
from typing import override

from unique_mcp.logging import configure_logging as configure_pino_logging

from backstop_mcp.config import AppConfig


class _DuplicateMcpMetricsFilter(logging.Filter):
    """Drop `unique_mcp` per-call lines. Metrics stay; our middleware writes the line."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        return not (hasattr(record, "operation") and hasattr(record, "duration_ms"))


class _FastMcpToolErrorFilter(logging.Filter):
    """Drop FastMCP's tool-error lines. They repeat ours and can include argument text."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.msg
        if not isinstance(message, str):
            return True
        return not (
            message.startswith("Error calling tool")
            or message.startswith("Invalid arguments for tool")
        )


class _FastMcpArgumentDumpFilter(logging.Filter):
    """Drop the debug line that prints the tool-call argument dict."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.msg
        if not isinstance(message, str):
            return True
        return (
            "Handler called: call_tool" not in message
            and "Handler called: get_prompt" not in message
        )


def configure_logging(config: AppConfig) -> None:
    configure_pino_logging(level=config.log_level.value.upper())
    # Python warnings otherwise reach stderr as plain text the log pipeline cannot parse.
    logging.captureWarnings(True)
    _reclaim("fastmcp")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # sse-starlette logs each outbound event body at DEBUG, which is the tool result.
    logging.getLogger("sse_starlette").setLevel(logging.INFO)
    _install("unique_mcp", _DuplicateMcpMetricsFilter)
    _install("fastmcp.server.server", _FastMcpToolErrorFilter)
    _install("fastmcp.server.mixins.mcp_operations", _FastMcpArgumentDumpFilter)


def _reclaim(name: str) -> None:
    """`fastmcp` installs its own stderr handler with `propagate=False` at import time."""
    reclaimed = logging.getLogger(name)
    for handler in list(reclaimed.handlers):
        reclaimed.removeHandler(handler)
    reclaimed.propagate = True
    reclaimed.setLevel(logging.NOTSET)


def _install(logger_name: str, filter_type: type[logging.Filter]) -> None:
    """One filter of each type. `create_app` runs many times in tests."""
    target = logging.getLogger(logger_name)
    if any(isinstance(existing, filter_type) for existing in target.filters):
        return
    target.addFilter(filter_type())
