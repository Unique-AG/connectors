import weakref
from typing import cast
from typing import override

from mcp_configs import ErrorDetailsPolicy
from mcp_configs import TraceExporter
from mcp_configs import TracingSettings
from opentelemetry import trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event
from opentelemetry.sdk.trace import Span
from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.util import BoundedList
from opentelemetry.trace import ProxyTracerProvider
from opentelemetry.trace import Status
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from mcp_observability.stacktrace import scrub_stacktrace

_redacted_providers: weakref.WeakSet[TracerProvider] = weakref.WeakSet()


def configure_tracing(
    settings: TracingSettings,
    *,
    service_name: str,
    service_version: str,
    error_details_policy: ErrorDetailsPolicy,
) -> bool:
    """Install the trace provider `settings` asks for, and propagate W3C trace context and
    baggage. False when tracing is off. Leaves a provider installed before it in place.

    Unless `error_details_policy` discloses them, every span the provider exports, one installed
    before this included, loses its exception messages and status description.
    """
    enabled = settings.exporter is not TraceExporter.NONE
    if enabled and isinstance(trace.get_tracer_provider(), ProxyTracerProvider):
        _install_provider(settings, service_name=service_name, service_version=service_version)
    provider = trace.get_tracer_provider()
    if (
        error_details_policy is ErrorDetailsPolicy.REDACT
        and isinstance(provider, TracerProvider)
        and provider not in _redacted_providers
    ):
        provider.add_span_processor(ErrorDetailsRedaction())
        _redacted_providers.add(provider)
    return enabled


class ErrorDetailsRedaction(SpanProcessor):
    """Cuts exception messages out of a span's events and status before export. The span has
    ended by then, so only its private `_status` and `_events` can still be replaced."""

    @override
    def _on_ending(self, span: Span) -> None:
        events = cast("BoundedList[Event]", span._events)  # pyright: ignore[reportPrivateUsage]
        # Unbounded: the span's event limit already applied to what it holds.
        redacted = cast("BoundedList[Event]", BoundedList(None))
        redacted.extend([_redacted(event) for event in events])
        span._events = redacted  # pyright: ignore[reportPrivateUsage]
        if span.status.description is not None:
            span._status = Status(span.status.status_code)  # pyright: ignore[reportPrivateUsage]


def _redacted(event: Event) -> Event:
    if event.name != "exception":
        return event
    attributes = {
        key: scrub_stacktrace(value)
        if key == "exception.stacktrace" and isinstance(value, str)
        else value
        for key, value in (event.attributes or {}).items()
        if key != "exception.message"
    }
    return Event(event.name, attributes, event.timestamp)


def _install_provider(
    settings: TracingSettings, *, service_name: str, service_version: str
) -> None:
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name, "service.version": service_version})
    )
    if settings.exporter is TraceExporter.CONSOLE:
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
