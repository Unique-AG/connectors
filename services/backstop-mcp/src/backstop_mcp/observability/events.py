"""Write a log line and put the same event on the active span, in one call."""

import logging

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import Status, StatusCode

from backstop_mcp.observability.failures import failure_level
from backstop_mcp.observability.fields import span_attributes

# Tells the redaction processor that the failure on this span was caller-caused. An ERROR on the
# same span, before or after, wins: a bug keeps its stack.
EXPECTED_FAILURE_ATTRIBUTE = "backstop.failure.expected"


def info_event(logger: logging.Logger, event: str, **fields: object) -> None:
    _emit(logger, logging.INFO, event, fields, exc=None)


def warning_event(
    logger: logging.Logger, event: str, *, exc: BaseException | None = None, **fields: object
) -> None:
    _emit(logger, logging.WARNING, event, fields, exc=exc)


def error_event(
    logger: logging.Logger, event: str, *, exc: BaseException | None = None, **fields: object
) -> None:
    _emit(logger, logging.ERROR, event, fields, exc=exc)


def failure_event(logger: logging.Logger, event: str, exc: BaseException, **fields: object) -> None:
    """`warning_event` or `error_event`, chosen by `failure_level(exc)`."""
    _emit(logger, failure_level(exc), event, fields, exc=exc)


def _emit(
    logger: logging.Logger,
    level: int,
    event: str,
    fields: dict[str, object],
    *,
    exc: BaseException | None,
) -> None:
    extra = fields if exc is None else {**fields, "error_type": type(exc).__qualname__}
    # Stack traces only at ERROR: a WARNING is by definition nothing a developer must act on.
    logger.log(level, event, extra=extra, exc_info=exc if level >= logging.ERROR else None)
    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.add_event(event, {**span_attributes(extra), "log.severity": logging.getLevelName(level)})
    if level >= logging.ERROR:
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
