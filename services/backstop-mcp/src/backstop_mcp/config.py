import os
import ssl
from enum import StrEnum
from importlib.metadata import version as pkg_version
from typing import ClassVar, TypedDict, cast
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

from pydantic import Field, PrivateAttr, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PKG_VERSION = pkg_version("backstop-mcp")

# libpq sslmode values that require certificate verification.
_SSLMODE_VERIFY = frozenset({"verify", "verify-ca", "verify-full"})
# Encrypt the connection but do not verify the server certificate.
_SSLMODE_ENCRYPT = frozenset({"require", "prefer"})


class AsyncpgConnectArgs(TypedDict, total=False):
    ssl: ssl.SSLContext


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


def _ssl_connect_arg(sslmode: str) -> ssl.SSLContext | None:
    """Map a libpq `sslmode` value to an asyncpg `ssl` connect argument."""
    if sslmode in ("disable", "allow"):
        return None
    if sslmode in _SSLMODE_ENCRYPT:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if sslmode in _SSLMODE_VERIFY:
        return ssl.create_default_context()
    raise ValueError(f"Unsupported sslmode={sslmode!r} in database URL")


def normalize_asyncpg_url(url: str) -> tuple[str, AsyncpgConnectArgs]:
    """Rewrite a libpq Postgres URL for SQLAlchemy/asyncpg.

    Helm injects `DATABASE_URL` with libpq query params (`sslmode=...`). asyncpg rejects
    those params, so strip them and return equivalent `connect_args` instead.
    """
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    parsed = urlparse(url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    sslmode = params.pop("sslmode", None)
    # Also libpq-only; asyncpg does not accept it in the query string.
    params.pop("channel_binding", None)

    clean_url = urlunparse(parsed._replace(query=urlencode(params)))
    connect_args: AsyncpgConnectArgs = {}
    if sslmode is not None:
        ssl_arg = _ssl_connect_arg(sslmode)
        if ssl_arg is not None:
            connect_args["ssl"] = ssl_arg
    return clean_url, connect_args


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

    Credentials are NOT configured here: each connecting MCP client completes the hosted
    login form (username + personal API token), which is verified against Backstop and then
    stored encrypted in Postgres. Tool calls load that per-user credential and send
    `Authorization: Basic ...` + `token: true` to Backstop. See `auth/provider.py`,
    `backstop_client.py`, and https://backstopsolutions.elevio.help/en/articles/1018 /
    .../236.

    Also carries the tuning knobs for the shared HTTP client: timeouts, per-user concurrency
    limits, retry behavior for 429s, and default pagination sizes.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="BACKSTOP_")

    base_url: str = "https://api.backstopsolutions.com"

    # httpx's undocumented default is ~5s; ordinary CRUD calls get a saner explicit timeout.
    default_timeout_seconds: float = Field(default=30.0, gt=0)
    # /reports and /{entity}/{id}/analytics can legitimately take up to ~30s per 500 records.
    reports_timeout_seconds: float = Field(default=120.0, gt=0)

    # Backstop hard-limits each user token to 5 concurrent connections.
    max_concurrent_requests_per_user: int = Field(default=5, ge=1)

    # Retry tuning for 429 (rate-limit) responses.
    max_retry_attempts: int = Field(default=5, ge=1)
    max_retry_wait_ms: int = Field(default=30_000, ge=0)

    # Default page size for `.paginate()` on ordinary CRUD collections.
    default_page_size: int = Field(default=100, ge=1)
    # Default page size for /reports and /analytics pagination; Backstop recommends not
    # exceeding 500 records per report page.
    report_page_size: int = Field(default=500, ge=1, le=500)


class DatabaseConfig(BaseSettings):
    """Where backstop-mcp stores OAuth clients/tokens and encrypted Backstop credentials."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="DB_")

    url: str | None = None
    host: str | None = None
    port: int = 5432
    name: str | None = None
    user: str | None = None
    password: str | None = None
    _connect_args: AsyncpgConnectArgs = PrivateAttr(default_factory=lambda: AsyncpgConnectArgs())

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
            self.url, self._connect_args = normalize_asyncpg_url(self.url)
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
        self._connect_args = AsyncpgConnectArgs()
        return self

    @property
    def connection_url(self) -> str:
        """Get the connection URL (guaranteed non-None after validation)."""
        if self.url is None:
            raise RuntimeError("URL should be set after validation")
        return self.url

    @property
    def connect_args(self) -> AsyncpgConnectArgs:
        """asyncpg connect args derived from libpq query params (e.g. sslmode)."""
        return self._connect_args


class EncryptionConfig(BaseSettings):
    """Key used to encrypt Backstop credentials (username + personal API token) at rest."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="BACKSTOP_MCP_")

    encryption_key: SecretStr | None = None

    @model_validator(mode="after")
    def _require_encryption_key(self) -> "EncryptionConfig":
        if self.encryption_key is None:
            raise ValueError("BACKSTOP_MCP_ENCRYPTION_KEY not set")
        return self
