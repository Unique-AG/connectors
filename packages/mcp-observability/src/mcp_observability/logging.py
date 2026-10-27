"""Pino-JSON logs on stderr, which Loki parses under the `pino-json` label."""

import json
import logging
import re
import sys
import traceback
from types import TracebackType
from typing import cast
from typing import override

from opentelemetry import trace

from mcp_observability.ops import OPS_PATHS

_ACCESS_PATH = re.compile(
    r'(?:^|[\s"])(?:GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)\s+([^?\s"]+)', re.IGNORECASE
)
_ACCESS_LOGGERS = ("uvicorn.access", "uvicorn.asgi")
_PINO_LEVEL = {
    logging.DEBUG: 20,
    logging.INFO: 30,
    logging.WARNING: 40,
    logging.ERROR: 50,
    logging.CRITICAL: 60,
}
# What every record carries, so the rest is what the call passed in `extra`.
_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message"}


def configure_logging(level: str) -> None:
    """Send every log record to stderr as Pino JSON, with the trace and span of the call, and
    drop the access log lines of the ops routes. Safe to call more than once."""
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(handler.formatter, PinoJsonFormatter) for handler in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(PinoJsonFormatter())
        root.addHandler(handler)
    for handler in root.handlers:
        handler.setLevel(level)
    for name in _ACCESS_LOGGERS:
        access = logging.getLogger(name)
        if not any(isinstance(kept, _QuietOpsRoutes) for kept in access.filters):
            access.addFilter(_QuietOpsRoutes())


class PinoJsonFormatter(logging.Formatter):
    @override
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": _PINO_LEVEL.get(record.levelno, 30),
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
        return json.dumps(payload, default=str, ensure_ascii=False)


class _QuietOpsRoutes(logging.Filter):
    @override
    def filter(self, record: logging.LogRecord) -> bool:
        match = _ACCESS_PATH.search(record.getMessage())
        return match is None or (match.group(1).rstrip("/") or "/") not in OPS_PATHS


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
