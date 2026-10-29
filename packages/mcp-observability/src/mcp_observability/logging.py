"""Pino-JSON logs on stderr, which Loki parses under the `pino-json` label."""

import copy
import json
import logging
import re
import sys
import traceback
from collections.abc import Iterable
from collections.abc import Sequence
from functools import partial
from types import TracebackType
from typing import cast
from typing import override

from mcp_configs import ErrorDetailsPolicy
from mcp_configs import LoggingSettings
from mcp_configs import LogLevel
from opentelemetry import trace

from mcp_observability.failed_fields import FAILED_FIELDS_SHOWN
from mcp_observability.failed_fields import failed_fields
from mcp_observability.ops import OPS_PATHS
from mcp_observability.redaction import SecretRedactor
from mcp_observability.redaction import failed_line
from mcp_observability.stacktrace import scrub_stacktrace

# httpx logs every request URL, query string included, at INFO. sse-starlette logs each outbound
# event body, which is the tool result, at DEBUG.
_DEFAULT_LIBRARY_LOG_LEVELS: dict[str, LogLevel] = {
    "httpx": LogLevel.WARNING,
    "httpcore": LogLevel.WARNING,
    "sse_starlette": LogLevel.INFO,
}

_ACCESS_PATH = re.compile(
    r'(?:^|[\s"])(?:GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)\s+([^?\s"]+)', re.IGNORECASE
)
_ACCESS_LOGGERS = ("uvicorn.access", "uvicorn.asgi")
# Loki's pino-json pipeline reads the number in `level`; `log_level` is the same level for people.
_PINO_LEVEL = {
    logging.DEBUG: (20, "debug"),
    logging.INFO: (30, "info"),
    logging.WARNING: (40, "warn"),
    logging.ERROR: (50, "error"),
    logging.CRITICAL: (60, "fatal"),
}
# What every record carries, so the rest is what the call passed in `extra`.
_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message"}


def configure_logging(
    settings: LoggingSettings,
    *,
    own_loggers: Sequence[str],
    secrets: Iterable[str] = (),
    secret_patterns: Iterable[re.Pattern[str]] = (),
    default_secret_patterns: bool = True,
) -> None:
    """Send every log record to stderr as Pino JSON, with the trace and span of the call, and
    without exception text unless `ERROR_DETAILS_POLICY=disclose`. Safe to call more than once.

    `secrets`, such as API keys from the settings, and `secret_patterns` are replaced with
    `[Redacted]` in every line, on top of the default patterns unless `default_secret_patterns` is
    false.

    `own_loggers` (the MCP's package, such as `("backstop_mcp",)`) and this package log at
    `LOG_LEVEL`; a library at its `LIBRARY_LOG_LEVELS` entry, else its default, else INFO. The app
    must run uvicorn with `log_config=None`, or uvicorn puts its own lines on plain-text handlers.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    output = next(
        (handler for handler in root.handlers if isinstance(handler.formatter, PinoJsonFormatter)),
        None,
    )
    if output is None:
        output = logging.StreamHandler(sys.stderr)
        root.addHandler(output)
    output.setFormatter(
        PinoJsonFormatter(
            SecretRedactor(secrets, secret_patterns, default_patterns=default_secret_patterns)
        )
    )
    output.setLevel(logging.NOTSET)
    for stale in [kept for kept in output.filters if isinstance(kept, _ErrorDetails)]:
        output.removeFilter(stale)
    output.addFilter(_ErrorDetails(settings.error_details_policy))

    _reclaim("fastmcp")
    for name in (*own_loggers, "mcp_observability"):
        logging.getLogger(name).setLevel(settings.log_level)
    for name, level in {**_DEFAULT_LIBRARY_LOG_LEVELS, **settings.library_log_levels}.items():
        logging.getLogger(name).setLevel(level)

    # Python warnings otherwise reach stderr as plain text the log pipeline cannot parse.
    logging.captureWarnings(True)
    add_filter_once("fastmcp.server.mixins.mcp_operations", _FastMcpArgumentDump)
    for name in _ACCESS_LOGGERS:
        add_filter_once(name, _QuietOpsRoutes)


class PinoJsonFormatter(logging.Formatter):
    def __init__(self, redactor: SecretRedactor | None = None) -> None:
        super().__init__()
        self._redactor: SecretRedactor = redactor or SecretRedactor()

    @override
    def format(self, record: logging.LogRecord) -> str:
        """Never raises: `logging` would print the record's message and arguments to stderr."""
        source = partial(_failure_source, record)
        try:
            line = json.dumps(self._payload(record), default=str, ensure_ascii=False)
        except Exception as error:  # noqa: BLE001 - any failure must still produce a safe line
            return failed_line("formatting", error, source=source)
        return self._redactor.redact_line(line, source=source)

    def _payload(self, record: logging.LogRecord) -> dict[str, object]:
        level, log_level = _PINO_LEVEL.get(record.levelno, _PINO_LEVEL[logging.INFO])
        payload: dict[str, object] = {
            "level": level,
            "log_level": log_level,
            "time": int(record.created * 1000),
            "msg": record.getMessage(),
            "context": record.name,
            **_trace_fields(),
            **{
                key: value
                for key, value in cast(dict[str, object], record.__dict__).items()
                if key not in _RECORD_FIELDS and not key.startswith("_")
            },
        }
        if record.exc_info and record.exc_info[0] is not None and "err" not in payload:
            payload["err"] = _error(*record.exc_info)
        return payload


class _ErrorDetails(logging.Filter):
    """Names the error on a record and, unless disclosed, drops its stack below ERROR and its
    messages at ERROR. Returns a copy, so another handler still sees the record as logged."""

    def __init__(self, policy: ErrorDetailsPolicy) -> None:
        super().__init__()
        self._policy: ErrorDetailsPolicy = policy

    @override
    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        error = record.exc_info[1] if record.exc_info else None
        if error is None:
            return record
        cleaned = copy.copy(record)
        cleaned.error_type = type(error).__qualname__
        if not hasattr(record, "failed_fields") and (fields := failed_fields([error])):
            cleaned.failed_fields = fields[:FAILED_FIELDS_SHOWN]
            cleaned.failed_field_count = len(fields)
        if record.levelno < logging.ERROR:
            cleaned.exc_info = None
            cleaned.exc_text = None
        elif self._policy is ErrorDetailsPolicy.REDACT and not hasattr(record, "err"):
            # The formatter writes its own `err`, message included, only when there is none.
            cleaned.err = {
                "name": type(error).__name__,
                "stack": scrub_stacktrace("".join(traceback.format_exception(error))),
            }
        return cleaned


class _FastMcpArgumentDump(logging.Filter):
    """FastMCP's DEBUG line for a tool call or prompt prints its argument dict."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.msg
        if not isinstance(message, str):
            return True
        return (
            "Handler called: call_tool" not in message
            and "Handler called: get_prompt" not in message
        )


class _QuietOpsRoutes(logging.Filter):
    @override
    def filter(self, record: logging.LogRecord) -> bool:
        match = _ACCESS_PATH.search(record.getMessage())
        return match is None or (match.group(1).rstrip("/") or "/") not in OPS_PATHS


def _reclaim(name: str) -> None:
    """`fastmcp` installs its own stderr handler with `propagate=False` at import time."""
    reclaimed = logging.getLogger(name)
    for handler in list(reclaimed.handlers):
        reclaimed.removeHandler(handler)
    reclaimed.propagate = True
    reclaimed.setLevel(logging.NOTSET)


def add_filter_once(logger_name: str, filter_type: type[logging.Filter]) -> None:
    target = logging.getLogger(logger_name)
    if not any(isinstance(existing, filter_type) for existing in target.filters):
        target.addFilter(filter_type())


def _failure_source(record: logging.LogRecord) -> dict[str, object]:
    """Where a log call that failed was made, for the line that replaces it. Only the logger, level,
    code location and trace ids: none of them holds a logged value."""
    level, _ = _PINO_LEVEL.get(record.levelno, _PINO_LEVEL[logging.INFO])
    return {
        "context": record.name,
        "original_level": level,
        "logged_from": f"{record.funcName} ({record.pathname}:{record.lineno})",
        **_trace_fields(),
    }


def _trace_fields() -> dict[str, str | int]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {}
    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
        "trace_flags": int(context.trace_flags),
    }


def _error(
    kind: type[BaseException], error: BaseException | None, stack: TracebackType | None
) -> dict[str, str]:
    return {
        "name": kind.__name__,
        "message": str(error),
        "stack": "".join(traceback.format_exception(kind, error, stack)),
    }
