from enum import StrEnum
from typing import ClassVar, cast

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_configs.config import shared_config


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DiagnosticsDataPolicy(StrEnum):
    """Whether identifying values in logs are printed or replaced by `sha256:<hex>`, which still
    correlates them across lines."""

    CONCEAL = "conceal"
    DISCLOSE = "disclose"


class ErrorDetailsPolicy(StrEnum):
    """Whether exception messages and stack text stay in logs and on spans. Separate from
    `DiagnosticsDataPolicy`, so reading an error while debugging does not disclose every login."""

    REDACT = "redact"
    DISCLOSE = "disclose"


class LoggingSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config()

    # The level of the MCP's own loggers.
    log_level: LogLevel = LogLevel.INFO
    # `{"httpx": "INFO"}`, merged over the defaults. A library not named logs at INFO.
    library_log_levels: dict[str, LogLevel] = {}
    diagnostics_data_policy: DiagnosticsDataPolicy = Field(
        default=DiagnosticsDataPolicy.CONCEAL,
        validation_alias="LOGS_DIAGNOSTICS_DATA_POLICY",
    )
    error_details_policy: ErrorDetailsPolicy = ErrorDetailsPolicy.REDACT

    @field_validator("log_level", mode="before")
    @classmethod
    def _uppercase(cls, value: object) -> object:
        """The charts set `LOG_LEVEL: info`."""
        return value.upper() if isinstance(value, str) else value

    @field_validator("library_log_levels", mode="before")
    @classmethod
    def _uppercase_each(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        levels = cast("dict[object, object]", value)
        return {
            name: level.upper() if isinstance(level, str) else level
            for name, level in levels.items()
        }

    @field_validator("diagnostics_data_policy", "error_details_policy", mode="before")
    @classmethod
    def _lowercase(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @property
    def discloses_diagnostics(self) -> bool:
        return self.diagnostics_data_policy is DiagnosticsDataPolicy.DISCLOSE

    @property
    def discloses_error_details(self) -> bool:
        return self.error_details_policy is ErrorDetailsPolicy.DISCLOSE
