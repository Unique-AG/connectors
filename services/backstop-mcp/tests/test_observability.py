"""The observability helpers: one log line and the same event on the active span."""

import logging
from typing import ClassVar

import httpx
import pytest
from fastmcp.exceptions import ToolError, ValidationError
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from backstop_mcp.observability import (
    DeclaresFailureLevel,
    add_call_fields,
    error_event,
    failure_level,
    info_event,
    operation,
    tool_call_scope,
    warning_event,
)
from backstop_mcp.utils import IdentifiableValue, PseudonymMode

logger = logging.getLogger(__name__)


class _Declared(Exception, DeclaresFailureLevel):
    failure_level: ClassVar[int] = logging.INFO


class TestInfoEvent:
    def test_logs_and_adds_the_same_attributes_to_the_current_span(
        self, caplog: pytest.LogCaptureFixture, exporter: InMemorySpanExporter
    ) -> None:
        caplog.set_level(logging.INFO)
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("parent"):
            info_event(logger, "widget.fetched", entity_id="p1", returned=2)

        record = next(item for item in caplog.records if item.message == "widget.fetched")
        assert record.levelno == logging.INFO
        assert record.entity_id == "p1"  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert record.returned == 2  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        span = next(item for item in exporter.get_finished_spans() if item.name == "parent")
        event = next(item for item in span.events if item.name == "widget.fetched")
        assert event.attributes is not None
        assert event.attributes["entity_id"] == "p1"
        assert event.attributes["returned"] == 2
        assert event.attributes["log.severity"] == "INFO"

    def test_outside_any_span_logs_and_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)

        info_event(logger, "widget.fetched", returned=0)

        assert any(item.message == "widget.fetched" for item in caplog.records)


class TestWarningAndErrorEvents:
    def test_warning_records_error_type_without_a_traceback_or_span_status(
        self, caplog: pytest.LogCaptureFixture, exporter: InMemorySpanExporter
    ) -> None:
        caplog.set_level(logging.INFO)
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("parent"):
            warning_event(logger, "widget.skipped", exc=ToolError("nope"), entity_id="p1")

        record = next(item for item in caplog.records if item.message == "widget.skipped")
        assert record.levelno == logging.WARNING
        assert record.error_type == "ToolError"  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert record.exc_info is None
        span = next(item for item in exporter.get_finished_spans() if item.name == "parent")
        assert span.status.status_code == StatusCode.UNSET

    def test_error_records_the_traceback_and_sets_span_status(
        self, caplog: pytest.LogCaptureFixture, exporter: InMemorySpanExporter
    ) -> None:
        caplog.set_level(logging.INFO)
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("parent"):
            error_event(logger, "widget.broken", exc=RuntimeError("boom"))

        record = next(item for item in caplog.records if item.message == "widget.broken")
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None
        span = next(item for item in exporter.get_finished_spans() if item.name == "parent")
        assert span.status.status_code == StatusCode.ERROR
        assert any(event.name == "exception" for event in span.events)


class TestPseudonymOnTheSpan:
    def test_an_identifiable_value_is_the_pseudonym_in_the_record_and_the_span(
        self, caplog: pytest.LogCaptureFixture, exporter: InMemorySpanExporter
    ) -> None:
        caplog.set_level(logging.INFO)
        wrapped = IdentifiableValue("mlucas", mode=PseudonymMode.PLAIN)
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("parent"):
            info_event(logger, "widget.fetched", login=wrapped)

        record = next(item for item in caplog.records if item.message == "widget.fetched")
        rendered = str(record.login)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]
        span = next(item for item in exporter.get_finished_spans() if item.name == "parent")
        event = next(item for item in span.events if item.name == "widget.fetched")
        assert event.attributes is not None
        assert "mlucas" not in rendered
        assert event.attributes["login"] == rendered


class TestFailureLevel:
    def test_plain_tool_error_is_warning(self) -> None:
        assert failure_level(ToolError("nope")) == logging.WARNING

    def test_tool_error_wrapping_a_bug_is_error(self) -> None:
        try:
            raise ToolError("wrapped") from KeyError("missing")
        except ToolError as exc:
            assert failure_level(exc) == logging.ERROR

    def test_validation_error_is_warning(self) -> None:
        assert failure_level(ValidationError("bad")) == logging.WARNING

    def test_read_timeout_is_warning(self) -> None:
        assert failure_level(httpx.ReadTimeout("slow")) == logging.WARNING

    def test_runtime_error_is_error(self) -> None:
        assert failure_level(RuntimeError("boom")) == logging.ERROR

    def test_a_declared_level_wins(self) -> None:
        assert failure_level(_Declared("quiet")) == logging.INFO


class TestOperation:
    def test_opens_a_child_span_and_logs_start_and_completed(
        self, caplog: pytest.LogCaptureFixture, exporter: InMemorySpanExporter
    ) -> None:
        caplog.set_level(logging.INFO)
        tracer = trace.get_tracer("test")

        with (
            tracer.start_as_current_span("parent"),
            operation(logger, "reports.fetch", report_id="r1") as outcome,
        ):
            outcome.record(rows=4)

        names = [item.message for item in caplog.records]
        assert "reports.fetch.start" in names
        completed = next(
            item for item in caplog.records if item.message == "reports.fetch.completed"
        )
        assert completed.rows == 4  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert completed.duration_ms >= 0  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        parent = next(item for item in exporter.get_finished_spans() if item.name == "parent")
        span = next(item for item in exporter.get_finished_spans() if item.name == "reports.fetch")
        assert span.attributes is not None
        assert span.attributes["rows"] == 4
        assert span.parent is not None
        assert parent.context is not None
        assert span.parent.span_id == parent.context.span_id

    def test_a_tool_error_logs_failed_at_warning_and_reraises(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)

        with pytest.raises(ToolError), operation(logger, "reports.fetch"):
            raise ToolError("nope")

        failed = next(item for item in caplog.records if item.message == "reports.fetch.failed")
        assert failed.levelno == logging.WARNING
        assert failed.exc_info is None
        assert not any(item.message == "reports.fetch.completed" for item in caplog.records)


class TestAddCallFields:
    def test_inside_a_scope_the_fields_are_collected(self) -> None:
        with tool_call_scope() as call:
            add_call_fields(returned=3, segment="people")

        assert call.fields == {"returned": 3, "segment": "people"}

    def test_outside_a_scope_it_collects_nothing(self) -> None:
        with tool_call_scope() as call:
            pass

        add_call_fields(returned=3)

        assert call.fields == {}
