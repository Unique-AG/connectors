"""Every `backstop_mcp` log line also becomes an event on the active span, so call sites log with
the standard `logging` API and nothing else.
"""

import logging
from typing import cast, override

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from backstop_mcp.observability.fields import span_attributes

_LOGGER_NAME = "backstop_mcp"
# What every record carries, so the rest is what the call passed in `extra`.
_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class SpanEventHandler(logging.Handler):
    """Adds the record to the active span as an event. An ERROR also records its exception and
    sets the span status.

    Then names the exception in `error_type` and, below ERROR, drops its stack: a WARNING is
    nothing a developer must act on. A logger calls its own handlers before its parents', so the
    output handlers on the root logger only ever see the record after this.
    """

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
    if record.levelno < logging.ERROR:
        return
    if exc is not None:
        span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, event))
