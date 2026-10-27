from enum import StrEnum
from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_configs.config import shared_config


class TraceExporter(StrEnum):
    NONE = "none"
    CONSOLE = "console"
    OTLP = "otlp"


class TracingSettings(BaseSettings):
    """OpenTelemetry tracing, off unless the environment turns it on. Reads the standard `OTEL_*`
    names, and the ones the Node services' charts set."""

    model_config: ClassVar[SettingsConfigDict] = shared_config("OTEL_")

    traces_exporter: TraceExporter | None = None
    # The full URL traces are sent to.
    otlp_traces_endpoint: str | None = Field(
        default=None, validation_alias="OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
    )
    # The collector's base URL, which every signal appends its own path to.
    otlp_endpoint: str | None = Field(default=None, validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    span_processor: TraceExporter | None = None
    enabled: bool | None = Field(default=None, validation_alias="ENABLE_OPENTELEMETRY")

    @property
    def traces_endpoint(self) -> str | None:
        """Where an OTLP exporter sends traces, as the OpenTelemetry spec resolves the two names.
        Passed to the exporter, since it reads only the process environment, not `.env`."""
        if self.otlp_traces_endpoint:
            return self.otlp_traces_endpoint
        if self.otlp_endpoint:
            return f"{self.otlp_endpoint.rstrip('/')}/v1/traces"
        return None

    @property
    def exporter(self) -> TraceExporter:
        """`OTEL_TRACES_EXPORTER` first, then an OTLP endpoint, then the Node services'
        `ENABLE_OPENTELEMETRY` with `OTEL_SPAN_PROCESSOR`."""
        if self.traces_exporter is not None:
            return self.traces_exporter
        if self.traces_endpoint:
            return TraceExporter.OTLP
        if self.enabled:
            return self.span_processor or TraceExporter.OTLP
        return TraceExporter.NONE
