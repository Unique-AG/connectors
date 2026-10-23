from enum import StrEnum
from typing import ClassVar

from pydantic import AliasChoices, Field
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
    otlp_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT"
        ),
    )
    span_processor: TraceExporter | None = None
    enabled: bool | None = Field(default=None, validation_alias="ENABLE_OPENTELEMETRY")

    @property
    def exporter(self) -> TraceExporter:
        """`OTEL_TRACES_EXPORTER` first, then an OTLP endpoint, then the Node services'
        `ENABLE_OPENTELEMETRY` with `OTEL_SPAN_PROCESSOR`."""
        if self.traces_exporter is not None:
            return self.traces_exporter
        if self.otlp_endpoint:
            return TraceExporter.OTLP
        if self.enabled:
            return self.span_processor or TraceExporter.OTLP
        return TraceExporter.NONE
