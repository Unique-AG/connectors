from collections.abc import Sequence
from typing import override

import pytest
from mcp_configs import TraceExporter
from mcp_configs import TracingSettings
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import ProxyTracerProvider

from mcp_observability import configure_tracing
from mcp_observability import tracing


def test_tracing_stays_off_when_the_settings_turn_it_off() -> None:
    settings = TracingSettings(traces_exporter=TraceExporter.NONE)

    assert not configure_tracing(settings, service_name="kiosk", service_version="1.0.0")


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_a_console_exporter_installs_a_provider_named_after_the_service() -> None:
    settings = TracingSettings(traces_exporter=TraceExporter.CONSOLE)

    assert configure_tracing(settings, service_name="kiosk", service_version="1.0.0")

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

    assert configure_tracing(settings, service_name="kiosk", service_version="1.0.0")

    assert [exporter.endpoint for exporter in exporters] == ["http://collector:4318/v1/traces"]
