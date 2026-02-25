from enum import Enum
from importlib.metadata import version as pkg_version
from typing import ClassVar
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PKG_VERSION = pkg_version("edgar-mcp")


def _validate_required_fields(
    fields: dict[str, str | None], url_field: str = "URL"
) -> list[str]:
    """Validate that required fields are not None.

    Args:
        fields: Mapping of field names to their values.
        url_field: Name of the URL field for error message (e.g., "DB_URL", "RABBITMQ_URL").

    Returns:
        List of missing field names.

    Raises:
        ValueError: If any required fields are missing.
    """
    missing = [name for name, val in fields.items() if val is None]
    if missing:
        raise ValueError(
            f"{url_field} not set; missing required fields: {', '.join(missing)}"
        )
    return missing


class AppEnv(str, Enum):
    """Application environment."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


class LogLevel(str, Enum):
    """Logging level."""

    FATAL = "fatal"
    ERROR = "error"
    WARN = "warn"
    INFO = "info"
    DEBUG = "debug"


class DiagnosticsDataPolicy(str, Enum):
    """Diagnostics data policy."""

    CONCEAL = "conceal"
    DISCLOSE = "disclose"


class AppConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict()

    app_env: AppEnv = AppEnv.PRODUCTION
    version: str = PKG_VERSION
    port: int = Field(default=9542, ge=0, le=65535)
    log_level: LogLevel = LogLevel.INFO
    logs_diagnostics_data_policy: DiagnosticsDataPolicy = DiagnosticsDataPolicy.CONCEAL


class DatabaseConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="DB_")

    url: str | None = None
    host: str | None = None
    port: int = 5432
    name: str | None = None
    user: str | None = None
    password: str | None = None

    @model_validator(mode="after")
    def build_url(self) -> "DatabaseConfig":
        if self.url is not None:
            if not self.url.startswith(("postgresql://", "postgresql+")):
                raise ValueError("DB_URL must be a PostgreSQL connection string (postgresql://...)")
            if self.url.startswith("postgresql://"):
                self.url = self.url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return self

        _validate_required_fields(
            {
                "DB_HOST": self.host,
                "DB_NAME": self.name,
                "DB_USER": self.user,
                "DB_PASSWORD": self.password,
            },
            url_field="DB_URL",
        )

        assert self.user is not None
        assert self.password is not None
        self.url = (
            f"postgresql+asyncpg://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.name}"
        )
        return self

    @property
    def connection_url(self) -> str:
        """Get the connection URL (guaranteed non-None after validation)."""
        if self.url is None:
            raise RuntimeError("URL should be set after validation")
        return self.url


class RabbitMqConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="RABBITMQ_")

    url: str | None = None
    host: str | None = None
    port: int = 5672
    user: str | None = None
    password: str | None = None
    vhost: str = "/"

    @model_validator(mode="after")
    def build_url(self) -> "RabbitMqConfig":
        if self.url is not None:
            if not self.url.startswith(("amqp://", "amqps://")):
                raise ValueError(
                    "RABBITMQ_URL must be an AMQP connection string (amqp://... or amqps://...)"
                )
            return self

        _validate_required_fields(
            {
                "RABBITMQ_HOST": self.host,
                "RABBITMQ_USER": self.user,
                "RABBITMQ_PASSWORD": self.password,
            },
            url_field="RABBITMQ_URL",
        )

        assert self.user is not None
        assert self.password is not None
        self.url = (
            f"amqp://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.vhost.lstrip('/')}"
        )
        return self

    @property
    def connection_url(self) -> str:
        """Get the connection URL (guaranteed non-None after validation)."""
        if self.url is None:
            raise RuntimeError("URL should be set after validation")
        return self.url
