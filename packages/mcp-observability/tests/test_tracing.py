import pytest
from mcp_configs import TraceExporter
from mcp_configs import TracingSettings
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from mcp_observability import configure_tracing


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
