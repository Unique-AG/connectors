"""Every `backstop_mcp` log line also becomes an event on the active span, so call sites log with
the standard `logging` API and nothing else.
"""

import logging
from typing import cast, override

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import Status, StatusCode

from backstop_mcp.observability.fields import span_attributes

_LOGGER_NAME = "backstop_mcp"
# Tells the redaction processor that the failure on this span was caller-caused. An ERROR on the
# same span, before or after, wins: a bug keeps its stack.
EXPECTED_FAILURE_ATTRIBUTE = "backstop.failure.expected"
# What every record carries, so the rest is what the call passed in `extra`.
_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class SpanEventHandler(logging.Handler):
    """Puts the record on the active span, then drops its stack below ERROR before the root
    logger's output handlers see it."""

    @override
    def emit(self, record: logging.LogRecord) -> None:
        exc = record.exc_info[1] if record.exc_info else None
        _add_to_span(record, exc)
        if exc is None:
            return
        record.error_type = type(exc).__qualname__
        if record.levelno < logging.ERROR:
            record.exc_info = None
            record.exc_text = None


def install_log_handlers() -> None:
    """Safe to call more than once: `create_app` runs many times in tests."""
    ours = logging.getLogger(_LOGGER_NAME)
    if not any(isinstance(handler, SpanEventHandler) for handler in ours.handlers):
        ours.addHandler(SpanEventHandler())


def _add_to_span(record: logging.LogRecord, exc: BaseException | None) -> None:
    span = trace.get_current_span()
    if not span.is_recording():
        return
    event = record.getMessage()
    fields = {
        key: value
        for key, value in cast("dict[str, object]", record.__dict__).items()
        if key not in _RECORD_FIELDS and not key.startswith("_")
    }
    if exc is not None:
        fields["error_type"] = type(exc).__qualname__
    span.add_event(event, {**span_attributes(fields), "log.severity": record.levelname})
    if record.levelno >= logging.ERROR:
        if exc is not None:
            span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, event))
        span.set_attribute(EXPECTED_FAILURE_ATTRIBUTE, False)
        return
    if exc is not None and not _logged_an_error(span):
        span.set_attribute(EXPECTED_FAILURE_ATTRIBUTE, True)


def _logged_an_error(span: trace.Span) -> bool:
    """Our own ERROR, not the span status: FastMCP sets ERROR for every exception a tool raises."""
    if not isinstance(span, ReadableSpan) or span.attributes is None:
        return False
    return span.attributes.get(EXPECTED_FAILURE_ATTRIBUTE) is False
