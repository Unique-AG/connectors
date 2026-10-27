from enum import StrEnum
from typing import ClassVar

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


class LoggingSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config()

    log_level: LogLevel = LogLevel.INFO
    diagnostics_data_policy: DiagnosticsDataPolicy = Field(
        default=DiagnosticsDataPolicy.CONCEAL,
        validation_alias="LOGS_DIAGNOSTICS_DATA_POLICY",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _uppercase(cls, value: object) -> object:
        """The charts set `LOG_LEVEL: info`."""
        return value.upper() if isinstance(value, str) else value

    @field_validator("diagnostics_data_policy", mode="before")
    @classmethod
    def _lowercase(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @property
    def discloses_diagnostics(self) -> bool:
        return self.diagnostics_data_policy is DiagnosticsDataPolicy.DISCLOSE
