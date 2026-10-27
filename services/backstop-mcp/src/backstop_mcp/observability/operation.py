"""Start and end of one noisy operation: a child span, an INFO line at each end."""

import logging
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager

from opentelemetry import trace

from backstop_mcp.observability.failures import failure_level
from backstop_mcp.observability.fields import span_attributes

_tracer = trace.get_tracer("backstop_mcp")


class OperationOutcome:
    """Fields learned inside the block, written on the closing line and on the span."""

    def __init__(self, span: trace.Span) -> None:
        self._span: trace.Span = span
        self._fields: dict[str, object] = {}

    def record(self, **fields: object) -> None:
        self._fields.update(fields)
        self._span.set_attributes(span_attributes(fields))

    @property
    def fields(self) -> Mapping[str, object]:
        return dict(self._fields)


@contextmanager
def operation(logger: logging.Logger, event: str, **fields: object) -> Generator[OperationOutcome]:
    started = time.monotonic()
    with _tracer.start_as_current_span(
        event,
        attributes=span_attributes(fields),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        logger.info(f"{event}.start", extra=fields)
        outcome = OperationOutcome(span)
        try:
            yield outcome
        except Exception as exc:
            logger.log(
                failure_level(exc),
                f"{event}.failed",
                exc_info=exc,
                extra={**fields, **outcome.fields, "duration_ms": _ms(started)},
            )
            raise
        logger.info(
            f"{event}.completed",
            extra={**fields, **outcome.fields, "duration_ms": _ms(started)},
        )


def _ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 1)
