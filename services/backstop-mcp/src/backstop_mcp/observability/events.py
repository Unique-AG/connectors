"""Write a log line and put the same event on the active span, in one call."""

import logging

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from backstop_mcp.observability.failures import failure_level
from backstop_mcp.observability.fields import span_attributes


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
