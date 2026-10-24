"""Drop caller-caused exceptions from spans before export, and every exception's message text from
the rest: a `ToolError` quotes the caller's input, a pydantic error quotes the record.
"""

import logging
import re
from collections.abc import Iterable
from typing import cast, override

import httpx
from fastmcp.exceptions import ToolError, ValidationError
from opentelemetry import trace
from opentelemetry.sdk.trace import Event, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.util import BoundedList
from opentelemetry.trace import Status, StatusCode

from backstop_mcp.observability.events import EXPECTED_FAILURE_ATTRIBUTE
from backstop_mcp.observability.failures import DeclaresFailureLevel

_EXCEPTION_EVENT = "exception"
_EXCEPTION_TYPE = "exception.type"
_EXCEPTION_MESSAGE = "exception.message"
_EXCEPTION_STACKTRACE = "exception.stacktrace"
_CAUSE_MARKERS = (
    "The above exception was the direct cause of the following exception",
    "During handling of the above exception, another exception occurred",
)
_TRACEBACK_HEADER = re.compile(r"^[ +|]*(?:Exception Group )?Traceback \(most recent call last\):$")
_GROUP_MARGIN = re.compile(r"^(?:[ ]*\| )?")
_GROUP_SEPARATOR = re.compile(r"^[ |]*\+[-+ .\d]*$")
_FRAME_PREFIX = '  File "'
_CODE_PREFIX = "    "
_EXCEPTION_TYPE_LINE = re.compile(r"^([A-Za-z_][\w.]*)(?::|$)")

_installed_providers: set[int] = set()


class CallerFailureRedaction(SpanProcessor):
    @override
    def _on_ending(self, span: Span) -> None:
        # `set_status` is ignored once the span has ended, which it has by the time this runs.
        if _is_expected_failure(span) or _only_expected_exception_events(span):
            _replace_events(span, [e for e in _span_events(span) if not _is_exception_event(e)])
            if span.status.status_code is StatusCode.ERROR:
                span._status = Status(StatusCode.UNSET)  # pyright: ignore[reportPrivateUsage]
            return
        events = _span_events(span)
        _replace_events(span, [_scrubbed(e) if _is_exception_event(e) else e for e in events])
        description = span.status.description
        if description is not None and description not in {e.name for e in events}:
            span._status = Status(span.status.status_code)  # pyright: ignore[reportPrivateUsage]


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
    if not exception_events:
        return False
    expected = _expected_exception_types()
    return all(_is_expected_exception_event(event, expected) for event in exception_events)


def _is_expected_exception_event(event: Event, expected: frozenset[str]) -> bool:
    attributes = event.attributes
    if attributes is None:
        return False
    exception_type = attributes.get(_EXCEPTION_TYPE)
    if not isinstance(exception_type, str) or exception_type not in expected:
        return False
    # A chained exception is how a bug gets wrapped: its stack is what a developer needs.
    stacktrace = attributes.get(_EXCEPTION_STACKTRACE)
    return not (isinstance(stacktrace, str) and any(m in stacktrace for m in _CAUSE_MARKERS))


def _expected_exception_types() -> frozenset[str]:
    """Walked on every check: error types defined after import (Backstop's) must count too."""
    names: set[str] = set()
    pending: list[type[BaseException]] = [ToolError, ValidationError, httpx.TransportError]
    pending.extend(cast("list[type[BaseException]]", DeclaresFailureLevel.__subclasses__()))
    seen: set[type[BaseException]] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if _declared_level(current) < logging.ERROR:
            names.add(f"{current.__module__}.{current.__qualname__}")
        pending.extend(current.__subclasses__())
    return frozenset(names)


def _declared_level(exception_type: type[BaseException]) -> int:
    if issubclass(exception_type, DeclaresFailureLevel):
        return exception_type.failure_level
    return logging.WARNING


def _span_events(span: Span) -> list[Event]:
    raw = span._events  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType, reportUnknownVariableType]
    return list(cast("Iterable[Event]", raw))


def _replace_events(span: Span, events: list[Event]) -> None:
    replacement = cast("BoundedList[Event]", BoundedList(None))
    replacement.extend(events)
    span._events = replacement  # pyright: ignore[reportPrivateUsage]


def _is_exception_event(event: Event) -> bool:
    return event.name == _EXCEPTION_EVENT


def _scrubbed(event: Event) -> Event:
    attributes = {
        key: _scrub_stacktrace(value)
        if key == _EXCEPTION_STACKTRACE and isinstance(value, str)
        else value
        for key, value in (event.attributes or {}).items()
        if key != _EXCEPTION_MESSAGE
    }
    return Event(event.name, attributes, event.timestamp)


def _scrub_stacktrace(stacktrace: str) -> str:
    """Keep the frames and each exception's type; drop each message, which can quote a payload."""
    kept: list[str] = []
    state = "expect_type"
    for line in stacktrace.splitlines():
        body = _GROUP_MARGIN.sub("", line, count=1)
        if (
            _TRACEBACK_HEADER.match(line)
            or body.rstrip(":") in _CAUSE_MARKERS
            or _GROUP_SEPARATOR.match(line)
        ):
            kept.append(line)
            state = "expect_type"
        elif state == "message":
            continue
        elif not body.strip():
            kept.append(line)
        elif body.startswith(_FRAME_PREFIX) or (state == "frame" and body.startswith(_CODE_PREFIX)):
            kept.append(line)
            state = "frame"
        elif type_line := _EXCEPTION_TYPE_LINE.match(body):
            kept.append(line[: len(line) - len(body)] + type_line.group(1))
            state = "message"
        else:
            state = "message"
    return "\n".join(kept)
