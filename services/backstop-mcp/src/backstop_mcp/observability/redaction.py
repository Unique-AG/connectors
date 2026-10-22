"""Drop caller-caused exception text from spans before they are exported.

FastMCP records every tool exception on its `tools/call` span, message and stack included.
A `ToolError` or validation failure often interpolates the input the caller sent. `failure_event`
marks those spans with `backstop.failure.expected`; this processor then removes the exception
events and the status description. An ERROR (a bug) is not marked, so its stack stays.

A nested span records the same exception on the way out, before the tool span is marked. A direct
`ToolError`, a validation error, or a transport error is still caller-caused there, so those
events are removed too. A `ToolError` raised from another exception keeps its stack: that is how
an unexpected failure is wrapped.
"""

from collections.abc import Iterable
from typing import cast, override

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import Event, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.util import BoundedList
from opentelemetry.trace import Status, StatusCode

from backstop_mcp.observability.events import EXPECTED_FAILURE_ATTRIBUTE

_EXCEPTION_EVENT = "exception"
_EXCEPTION_TYPE = "exception.type"
_EXCEPTION_STACKTRACE = "exception.stacktrace"
_TOOL_ERROR = "fastmcp.exceptions.ToolError"
_VALIDATION_ERROR = "fastmcp.exceptions.ValidationError"
_CAUSE_MARKERS = (
    "The above exception was the direct cause of the following exception",
    "During handling of the above exception, another exception occurred",
)

_installed_providers: set[int] = set()


class CallerFailureRedaction(SpanProcessor):
    """Strip exception text from spans marked as expected failures."""

    @override
    def _on_ending(self, span: Span) -> None:
        if not _is_expected_failure(span) and not _only_expected_exception_events(span):
            return
        _drop_exception_events(span)
        description = span.status.description
        if description:
            # Direct assignment: `set_status(UNSET)` is ignored once a status was set, and the
            # span has already ended by the time processors run.
            span._status = Status(StatusCode.UNSET)  # pyright: ignore[reportPrivateUsage]


def install_caller_failure_redaction() -> None:
    """Attach the processor once to the active SDK provider. No-op without one."""
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        return
    identity = id(provider)
    if identity in _installed_providers:
        return
    provider.add_span_processor(CallerFailureRedaction())
    _installed_providers.add(identity)


def _is_expected_failure(span: Span) -> bool:
    attributes = span.attributes
    if attributes is None:
        return False
    return attributes.get(EXPECTED_FAILURE_ATTRIBUTE) is True


def _only_expected_exception_events(span: Span) -> bool:
    exception_events = [event for event in _span_events(span) if _is_exception_event(event)]
    return bool(exception_events) and all(
        _is_expected_exception_event(event) for event in exception_events
    )


def _is_expected_exception_event(event: Event) -> bool:
    attributes = event.attributes
    if attributes is None:
        return False
    exception_type = attributes.get(_EXCEPTION_TYPE)
    if not isinstance(exception_type, str):
        return False
    if exception_type == _VALIDATION_ERROR or exception_type in _transport_error_types():
        return True
    if exception_type != _TOOL_ERROR:
        return False
    stacktrace = attributes.get(_EXCEPTION_STACKTRACE)
    if not isinstance(stacktrace, str):
        return True
    return not any(marker in stacktrace for marker in _CAUSE_MARKERS)


def _transport_error_types() -> frozenset[str]:
    names: set[str] = set()
    pending: list[type[BaseException]] = [httpx.TransportError]
    while pending:
        current = pending.pop()
        names.add(f"{current.__module__}.{current.__qualname__}")
        pending.extend(current.__subclasses__())
    return frozenset(names)


def _span_events(span: Span) -> list[Event]:
    raw = span._events  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType, reportUnknownVariableType]
    return list(cast("Iterable[Event]", raw))


def _drop_exception_events(span: Span) -> None:
    kept = [event for event in _span_events(span) if not _is_exception_event(event)]
    replacement = cast("BoundedList[Event]", BoundedList(None))
    replacement.extend(kept)
    span._events = replacement  # pyright: ignore[reportPrivateUsage]


def _is_exception_event(event: Event) -> bool:
    if event.name != _EXCEPTION_EVENT:
        return False
    attributes = event.attributes
    if attributes is None:
        return True
    raw = attributes.get(_EXCEPTION_TYPE)
    return raw is None or isinstance(raw, str)
