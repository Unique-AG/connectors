from collections.abc import Callable
from collections.abc import Sequence
from typing import override

import pydantic
import pytest
from fastmcp.exceptions import ToolError
from mcp_configs import ErrorDetailsPolicy
from mcp_configs import TraceExporter
from mcp_configs import TracingSettings
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import ProxyTracerProvider
from opentelemetry.trace import Status
from opentelemetry.trace import StatusCode

from mcp_observability import configure_tracing
from mcp_observability import tracing

_CANARY = "zq-canary-value"
_REDACT = ErrorDetailsPolicy.REDACT


def test_tracing_stays_off_when_the_settings_turn_it_off() -> None:
    settings = TracingSettings(traces_exporter=TraceExporter.NONE)

    assert not configure_tracing(
        settings, service_name="kiosk", service_version="1.0.0", error_details_policy=_REDACT
    )


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_a_console_exporter_installs_a_provider_named_after_the_service() -> None:
    settings = TracingSettings(traces_exporter=TraceExporter.CONSOLE)

    assert configure_tracing(
        settings, service_name="kiosk", service_version="1.0.0", error_details_policy=_REDACT
    )

    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    assert provider.resource.attributes["service.name"] == "kiosk"
    assert provider.resource.attributes["service.version"] == "1.0.0"


class RecordingExporter(SpanExporter):
    """Stands in for `OTLPSpanExporter`, keeping the endpoint it was given."""

    def __init__(self, *, endpoint: str | None = None) -> None:
        self.endpoint: str | None = endpoint

    @override
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return SpanExportResult.SUCCESS


def test_an_otlp_exporter_sends_to_the_endpoint_the_settings_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exporter reads only the process environment, so an endpoint from `.env` reaches it
    through the settings alone."""
    exporters: list[RecordingExporter] = []
    installed: list[trace.TracerProvider] = []

    def recording_exporter(*, endpoint: str | None = None) -> RecordingExporter:
        exporters.append(RecordingExporter(endpoint=endpoint))
        return exporters[-1]

    monkeypatch.setattr(tracing, "OTLPSpanExporter", recording_exporter)
    monkeypatch.setattr(trace, "get_tracer_provider", ProxyTracerProvider)
    monkeypatch.setattr(trace, "set_tracer_provider", installed.append)
    settings = TracingSettings(otlp_endpoint="http://collector:4318")

    assert configure_tracing(
        settings, service_name="kiosk", service_version="1.0.0", error_details_policy=_REDACT
    )

    assert [exporter.endpoint for exporter in exporters] == ["http://collector:4318/v1/traces"]


class Till(pydantic.BaseModel):
    label: str


def _tool_error() -> BaseException:
    try:
        raise ToolError(f"No till named {_CANARY}")
    except ToolError as error:
        return error


def _validation_error() -> BaseException:
    try:
        Till.model_validate({"label": {_CANARY: _CANARY}})
    except pydantic.ValidationError as error:
        return error
    raise AssertionError("valid")


def _chained_error() -> BaseException:
    try:
        try:
            raise KeyError(_CANARY)
        except KeyError as cause:
            raise RuntimeError(_CANARY) from cause
    except RuntimeError as error:
        return error


def _exported(provider: TracerProvider, error: BaseException) -> ReadableSpan:
    """A span that failed the way FastMCP records a tool's exception."""
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("test").start_as_current_span(
        "tools/call sell", record_exception=False, set_status_on_exception=False
    ) as span:
        span.add_event("Till opened", {"till": 3})
        span.record_exception(error)
        span.set_status(Status(StatusCode.ERROR, str(error)))
    (exported,) = exporter.get_finished_spans()
    return exported


def _installed(monkeypatch: pytest.MonkeyPatch, policy: ErrorDetailsPolicy) -> TracerProvider:
    """`configure_tracing` on a provider installed before it, as a test harness does."""
    provider = TracerProvider()
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    settings = TracingSettings(traces_exporter=TraceExporter.NONE)
    configure_tracing(
        settings, service_name="kiosk", service_version="1.0.0", error_details_policy=policy
    )
    return provider


_ERRORS: list[Callable[[], BaseException]] = [_tool_error, _validation_error, _chained_error]


@pytest.mark.parametrize("error", _ERRORS)
def test_redact_keeps_the_exception_type_and_frames_but_no_text(
    monkeypatch: pytest.MonkeyPatch, error: Callable[[], BaseException]
) -> None:
    raised = error()

    span = _exported(_installed(monkeypatch, _REDACT), raised)

    (event,) = [event for event in span.events if event.name == "exception"]
    assert event.attributes is not None
    assert str(event.attributes["exception.type"]).endswith(type(raised).__qualname__)
    assert "exception.message" not in event.attributes
    assert "Traceback" in str(event.attributes["exception.stacktrace"])
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description is None
    assert _CANARY not in str(span.to_json())


def test_redact_keeps_the_other_events(monkeypatch: pytest.MonkeyPatch) -> None:
    span = _exported(_installed(monkeypatch, _REDACT), _tool_error())

    assert [event.name for event in span.events] == ["Till opened", "exception"]
    assert span.events[0].attributes == {"till": 3}


def test_redact_keeps_the_frames_and_types_of_a_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    span = _exported(_installed(monkeypatch, _REDACT), _chained_error())

    (event,) = [event for event in span.events if event.name == "exception"]
    assert event.attributes is not None
    stack = str(event.attributes["exception.stacktrace"])
    assert "\nKeyError\n" in stack
    assert "direct cause" in stack


@pytest.mark.parametrize("error", _ERRORS)
def test_disclose_keeps_the_exception_text(
    monkeypatch: pytest.MonkeyPatch, error: Callable[[], BaseException]
) -> None:
    span = _exported(_installed(monkeypatch, ErrorDetailsPolicy.DISCLOSE), error())

    assert _CANARY in str(span.to_json())
    assert span.status.description is not None


def test_configuring_twice_redacts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _installed(monkeypatch, _REDACT)
    settings = TracingSettings(traces_exporter=TraceExporter.NONE)

    configure_tracing(
        settings, service_name="kiosk", service_version="1.0.0", error_details_policy=_REDACT
    )

    processors = provider._active_span_processor._span_processors  # pyright: ignore[reportPrivateUsage]
    assert sum(isinstance(p, tracing.ErrorDetailsRedaction) for p in processors) == 1
