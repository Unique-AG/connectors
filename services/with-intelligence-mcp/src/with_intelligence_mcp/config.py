"""Service configuration."""

import os
import ssl
from datetime import timedelta
from enum import StrEnum
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import ClassVar, Literal, Self, TypedDict, cast

from pydantic import (
    Field,
    HttpUrl,
    PostgresDsn,
    PrivateAttr,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import URL, make_url

PKG_VERSION = pkg_version("with-intelligence-mcp")


type PlaintextSslMode = Literal["disable", "allow"]


class AsyncpgConnectArgs(TypedDict, total=False):
    ssl: ssl.SSLContext | PlaintextSslMode


def _ssl_connect_arg(sslmode: str, cafile: Path | None) -> ssl.SSLContext | PlaintextSslMode:
    # asyncpg parses these like libpq; leaving `ssl` unset would make it fall back to prefer.
    if sslmode == "disable" or sslmode == "allow":
        return sslmode
    if sslmode in ("require", "prefer"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if sslmode == "verify-ca":
        # libpq verify-ca checks the CA chain only; verify-full adds the hostname.
        ctx = ssl.create_default_context(cafile=cafile)
        ctx.check_hostname = False
        return ctx
    if sslmode in ("verify", "verify-full"):
        return ssl.create_default_context(cafile=cafile)
    raise ValueError(f"Unsupported sslmode={sslmode!r} for the database connection")


def _asyncpg_connect_args(sslmode: str | None, cafile: Path | None) -> AsyncpgConnectArgs:
    if sslmode is None:
        return AsyncpgConnectArgs()
    return AsyncpgConnectArgs(ssl=_ssl_connect_arg(sslmode, cafile))


def _query_param(query: dict[str, str | tuple[str, ...]], key: str) -> str | None:
    value = query.get(key)
    if value is None:
        return None
    if isinstance(value, tuple):
        return value[0] if value else None
    return value


def normalize_asyncpg_url(
    url: str, default_sslmode: str | None = None, cafile: Path | None = None
) -> tuple[str, AsyncpgConnectArgs]:
    """Rewrite a libpq PostgreSQL URL for asyncpg. The URL's own `sslmode` wins over the default."""
    parsed = make_url(url)
    if parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+asyncpg")
    elif not parsed.drivername.startswith("postgresql"):
        raise ValueError("DB_URL must be a PostgreSQL connection string (postgresql://...)")

    sslmode = _query_param(dict(parsed.query), "sslmode") or default_sslmode
    parsed = parsed.difference_update_query(["sslmode", "channel_binding"])
    return parsed.render_as_string(hide_password=False), _asyncpg_connect_args(sslmode, cafile)


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


# Hosts that cannot represent an externally reachable service.
_NON_PUBLIC_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "::"})


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AppConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict()

    app_env: AppEnv = AppEnv.PRODUCTION
    version: str = PKG_VERSION
    port: int = Field(default=9011, ge=0, le=65535)
    log_level: LogLevel = LogLevel.INFO
    public_base_url: HttpUrl = HttpUrl("http://localhost:9011")

    @model_validator(mode="after")
    def _require_public_https_base_url_in_production(self) -> Self:
        """Reject local public URLs in production."""
        if self.app_env != AppEnv.PRODUCTION:
            return self
        if self.public_base_url.scheme != "https":
            raise ValueError("PUBLIC_BASE_URL must use HTTPS in production")
        host = self.public_base_url.host
        assert host is not None, f"validated HttpUrl without a host: {self.public_base_url}"
        if host in _NON_PUBLIC_HOSTS:
            raise ValueError(
                "PUBLIC_BASE_URL must be this service's externally-reachable URL in "
                + f"{AppEnv.PRODUCTION} (got {self.public_base_url}); it is the OAuth issuer "
                + "clients are redirected to"
            )
        return self

    @property
    def issuer(self) -> str:
        """Return `public_base_url` without a trailing slash."""
        return str(self.public_base_url).rstrip("/")


# With Intelligence asset-class package identifiers.
class AssetClassGroup(StrEnum):
    """Values the v3 `asset_class_group` query parameter accepts. Unique licenses HFM + SFO."""

    HFM = "hfm"
    PEFI = "pefi"
    PCFI = "pcfi"
    REFI = "refi"
    CWI = "cwi"
    IWI = "iwi"
    SFO = "sfo"


class WithIntelligenceConfig(BaseSettings):
    """With Intelligence v3 API transport settings."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="WITH_INTELLIGENCE_")

    base_url: str = "https://api.withintelligence.com"

    @field_validator("base_url")
    @classmethod
    def _require_https_base_url(cls, value: str) -> str:
        parsed = HttpUrl(value)
        if parsed.scheme != "https":
            raise ValueError("WITH_INTELLIGENCE_BASE_URL must use HTTPS")
        return str(parsed).rstrip("/")

    asset_class_groups: tuple[AssetClassGroup, ...] = (AssetClassGroup.HFM,)

    default_timeout_seconds: float = Field(default=30.0, gt=0)

    default_page_size: int = Field(default=50, ge=1, le=500)

    # Our own politeness bound: With Intelligence publishes no concurrency limit,
    # only 429 on every path.
    max_concurrent_requests_per_user: int = Field(default=5, ge=1)

    max_retry_attempts: int = Field(default=3, ge=1)
    max_retry_wait_ms: int = Field(default=8_000, ge=0)


class DatabaseConfig(BaseSettings):
    """Database connection settings."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="DB_")

    url: PostgresDsn | None = None
    host: str | None = None
    port: int = 5432
    name: str | None = None
    user: str | None = None
    password: str | None = None
    # The base Helm chart sends sslmode separately: CloudNativePG's `fqdn-uri` carries none.
    ssl_mode: str | None = Field(default=None, validation_alias="PG_DATABASE_SSL_MODE")
    ssl_root_cert: Path | None = None
    _connection_url: str = PrivateAttr(default="")
    _connect_args: AsyncpgConnectArgs = PrivateAttr(default_factory=lambda: AsyncpgConnectArgs())

    @model_validator(mode="before")
    @classmethod
    def accept_database_url(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        values = cast(dict[str, object], data)
        if values.get("url") is None:
            database_url = os.environ.get("DATABASE_URL")
            if database_url:
                return {**values, "url": database_url}
        return values

    @model_validator(mode="after")
    def _resolve_connection_url(self) -> Self:
        if self.url is not None:
            self._connection_url, self._connect_args = normalize_asyncpg_url(
                str(self.url), self.ssl_mode, self._ssl_cafile
            )
            return self

        missing = [
            name
            for name, val in (
                ("DB_HOST", self.host),
                ("DB_NAME", self.name),
                ("DB_USER", self.user),
                ("DB_PASSWORD", self.password),
            )
            if val is None
        ]
        if missing:
            raise ValueError(f"DB_URL not set; missing required fields: {', '.join(missing)}")

        self._connection_url = URL.create(
            drivername="postgresql+asyncpg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.name,
        ).render_as_string(hide_password=False)
        self._connect_args = _asyncpg_connect_args(self.ssl_mode, self._ssl_cafile)
        return self

    @property
    def _ssl_cafile(self) -> Path | None:
        # The chart mounts the CloudNativePG CA Secret as optional, so on a managed Postgres the
        # file is absent and the server is verified against the system trust store instead.
        if self.ssl_root_cert is None or not self.ssl_root_cert.is_file():
            return None
        return self.ssl_root_cert

    @property
    def connection_url(self) -> str:
        return self._connection_url

    @property
    def connect_args(self) -> AsyncpgConnectArgs:
        return self._connect_args


class AuthConfig(BaseSettings):
    """OAuth retention, cleanup, and login throttling settings."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="AUTH_")

    token_retention_days: int = Field(default=30, ge=1)
    unused_client_retention_hours: float = Field(default=24.0, gt=0)

    cleanup_interval_hours: float = Field(default=6.0, gt=0)
    login_max_attempts: int = Field(default=10, ge=1)
    login_attempt_window_minutes: int = Field(default=15, ge=1)

    @property
    def token_retention(self) -> timedelta:
        return timedelta(days=self.token_retention_days)

    @property
    def unused_client_retention(self) -> timedelta:
        return timedelta(hours=self.unused_client_retention_hours)

    @property
    def cleanup_interval(self) -> timedelta:
        return timedelta(hours=self.cleanup_interval_hours)

    @property
    def login_attempt_window(self) -> timedelta:
        return timedelta(minutes=self.login_attempt_window_minutes)


class EncryptionConfig(BaseSettings):
    """Key used to encrypt stored WI sessions at rest."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WITH_INTELLIGENCE_MCP_"
    )

    encryption_key: SecretStr | None = None

    @model_validator(mode="after")
    def _require_encryption_key(self) -> Self:
        if self.encryption_key is None:
            raise ValueError("WITH_INTELLIGENCE_MCP_ENCRYPTION_KEY not set")
        return self
