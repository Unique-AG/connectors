import os
from enum import StrEnum
from importlib.metadata import version as pkg_version
from typing import ClassVar, cast
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PKG_VERSION = pkg_version("backstop-mcp")


def _validate_required_fields(fields: dict[str, str | None], url_field: str = "URL") -> None:
    """Validate that required fields are not None.

    Args:
        fields: Mapping of field names to their values.
        url_field: Name of the URL field for the error message (e.g. "DB_URL").

    Raises:
        ValueError: If any required fields are missing.
    """
    missing = [name for name, val in fields.items() if val is None]
    if missing:
        raise ValueError(f"{url_field} not set; missing required fields: {', '.join(missing)}")


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


class LogLevel(StrEnum):
    FATAL = "fatal"
    ERROR = "error"
    WARN = "warn"
    INFO = "info"
    DEBUG = "debug"


class AppConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict()

    app_env: AppEnv = AppEnv.PRODUCTION
    version: str = PKG_VERSION
    port: int = Field(default=9010, ge=0, le=65535)
    log_level: LogLevel = LogLevel.INFO

    # The externally-reachable URL of this service — used as the OAuth issuer/base URL
    # (discovery metadata, /authorize, /token, and the Backstop login form all hang off it).
    # Must be set to the real public URL in any deployed environment.
    public_base_url: str = "http://localhost:9010"


class BackstopConfig(BaseSettings):
    """Where to reach the Backstop REST API.

    Credentials are NOT configured here: each connecting MCP client authenticates as
    themselves by sending their own Backstop `Authorization: Basic ...` (and, for SSO
    users, `token: true`) header, which is forwarded to Backstop unchanged. See
    `backstop_client.py`, and https://backstopsolutions.elevio.help/en/articles/1018 /
    .../236.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="BACKSTOP_")

    base_url: str = "https://api.backstopsolutions.com"


class DatabaseConfig(BaseSettings):
    """Where backstop-mcp stores OAuth clients/tokens and encrypted Backstop credentials."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="DB_")

    url: str | None = None
    host: str | None = None
    port: int = 5432
    name: str | None = None
    user: str | None = None
    password: str | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_database_url(cls, data: object) -> object:
        """Accept DATABASE_URL (injected by the base Helm chart) as an alias for DB_URL."""
        if not isinstance(data, dict):
            return data
        values = cast(dict[str, object], data)
        if values.get("url") is None:
            database_url = os.environ.get("DATABASE_URL")
            if database_url:
                return {**values, "url": database_url}
        return values

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


class EncryptionConfig(BaseSettings):
    """Key used to encrypt Backstop credentials (username + personal API token) at rest."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="BACKSTOP_MCP_")

    encryption_key: SecretStr | None = None

    @model_validator(mode="after")
    def _require_encryption_key(self) -> "EncryptionConfig":
        if self.encryption_key is None:
            raise ValueError("BACKSTOP_MCP_ENCRYPTION_KEY not set")
        return self
