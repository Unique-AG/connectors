from mcp_configs import TraceExporter
from mcp_configs import TracingSettings
from opentelemetry import trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import ProxyTracerProvider
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


def configure_tracing(
    settings: TracingSettings, *, service_name: str, service_version: str
) -> bool:
    """Install the trace provider `settings` asks for, and propagate W3C trace context and
    baggage. False when tracing is off. Leaves a provider installed before it in place."""
    exporter = settings.exporter
    if exporter is TraceExporter.NONE:
        return False
    if not isinstance(trace.get_tracer_provider(), ProxyTracerProvider):
        return True
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name, "service.version": service_version})
    )
    if exporter is TraceExporter.CONSOLE:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        # The sizing of the Node services' instrumentation.ts.
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=settings.traces_endpoint),
                max_queue_size=2048,
                max_export_batch_size=512,
                schedule_delay_millis=5000,
            )
        )
    trace.set_tracer_provider(provider)
    set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )
    return True
