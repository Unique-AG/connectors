"""Caller-caused exception text leaves a span before export; a bug keeps its stack."""

import logging
from typing import ClassVar

import httpx
import pytest
from fastmcp.exceptions import ToolError
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

from backstop_mcp.observability import DeclaresFailureLevel

# Under `backstop_mcp`, where `install_log_handlers` attaches the span handler.
logger = logging.getLogger("backstop_mcp.tests.redaction")

_CANARY = "zq-canary-stage"


class _UpstreamRejected(ToolError):
    """Stands in for `BackstopApiError`: a `ToolError` subclass with no declared level."""


class _QuietUpstream(Exception, DeclaresFailureLevel):
    failure_level: ClassVar[int] = logging.WARNING


class _SchemaDrift(ToolError, DeclaresFailureLevel):
    failure_level: ClassVar[int] = logging.ERROR


def _span(exporter: InMemorySpanExporter, name: str) -> ReadableSpan:
    return next(item for item in exporter.get_finished_spans() if item.name == name)


def _has_exception_event(span: ReadableSpan) -> bool:
    return any(event.name == "exception" for event in span.events)


class TestNestedSpans:
    @pytest.mark.parametrize(
        "error",
        [
            ToolError(f"unknown stage {_CANARY}"),
            _UpstreamRejected(f"Backstop API error (422): {_CANARY}"),
            _QuietUpstream(_CANARY),
            httpx.ReadTimeout(_CANARY),
        ],
        ids=["tool-error", "tool-error-subclass", "declared-warning", "transport"],
    )
    def test_a_caller_caused_exception_leaves_no_text(
        self, exporter: InMemorySpanExporter, error: Exception
    ) -> None:
        tracer = trace.get_tracer("test")

        with pytest.raises(type(error)), tracer.start_as_current_span("inner"):
            raise error

        span = _span(exporter, "inner")
        assert not _has_exception_event(span)
        assert span.status.status_code == StatusCode.UNSET
        assert span.status.description is None

    def test_a_tool_error_wrapping_a_bug_keeps_its_stack(
        self, exporter: InMemorySpanExporter
    ) -> None:
        tracer = trace.get_tracer("test")

        with pytest.raises(ToolError), tracer.start_as_current_span("inner"):
            try:
                raise KeyError("missing")
            except KeyError as exc:
                raise ToolError("wrapped") from exc

        span = _span(exporter, "inner")
        assert span.status.status_code == StatusCode.ERROR
        assert _has_exception_event(span)

    def test_a_tool_error_declared_error_keeps_its_stack(
        self, exporter: InMemorySpanExporter
    ) -> None:
        tracer = trace.get_tracer("test")

        with pytest.raises(_SchemaDrift), tracer.start_as_current_span("inner"):
            raise _SchemaDrift("response no longer matches")

        span = _span(exporter, "inner")
        assert span.status.status_code == StatusCode.ERROR
        assert _has_exception_event(span)


class TestMarkedSpans:
    def test_a_warning_marks_the_span_and_its_exception_text_is_dropped(
        self, exporter: InMemorySpanExporter
    ) -> None:
        tracer = trace.get_tracer("test")

        with tracer.start_as_current_span("tool") as span:
            failure = RuntimeError(_CANARY)
            logger.warning("tool.call.failed", exc_info=failure)
            # What FastMCP does on its tool span after our middleware logged the failure.
            span.record_exception(failure)

        exported = _span(exporter, "tool")
        assert not _has_exception_event(exported)
        assert _CANARY not in str(exported.events)

    def test_a_warning_after_fastmcp_set_error_status_still_marks_the_span(
        self, exporter: InMemorySpanExporter
    ) -> None:
        tracer = trace.get_tracer("test")

        with tracer.start_as_current_span("tool") as span:
            failure = RuntimeError(_CANARY)
            # FastMCP records the exception and sets ERROR before our middleware sees it.
            span.record_exception(failure)
            span.set_status(Status(StatusCode.ERROR, _CANARY))
            logger.warning("tool.call.failed", exc_info=failure)

        exported = _span(exporter, "tool")
        assert not _has_exception_event(exported)
        assert exported.status.status_code == StatusCode.UNSET

    def test_a_bug_after_a_coped_warning_keeps_its_stack(
        self, exporter: InMemorySpanExporter
    ) -> None:
        tracer = trace.get_tracer("test")

        with tracer.start_as_current_span("tool"):
            logger.warning("catalog.stale_served", exc_info=httpx.ReadTimeout("slow"))
            logger.error("tool.call.failed", exc_info=KeyError("missing"))

        exported = _span(exporter, "tool")
        assert exported.status.status_code == StatusCode.ERROR
        assert _has_exception_event(exported)

    def test_a_coped_warning_after_a_bug_keeps_its_stack(
        self, exporter: InMemorySpanExporter
    ) -> None:
        tracer = trace.get_tracer("test")

        with tracer.start_as_current_span("tool"):
            logger.error("widget.broken", exc_info=KeyError("missing"))
            logger.warning("catalog.stale_served", exc_info=httpx.ReadTimeout("slow"))

        exported = _span(exporter, "tool")
        assert exported.status.status_code == StatusCode.ERROR
        assert _has_exception_event(exported)
