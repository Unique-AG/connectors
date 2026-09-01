import os
import ssl
from datetime import timedelta
from enum import StrEnum
from importlib.metadata import version as pkg_version
from typing import ClassVar, Self, TypedDict, cast

from pydantic import Field, HttpUrl, PostgresDsn, PrivateAttr, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import URL, make_url

PKG_VERSION = pkg_version("with-intelligence-mcp")


class AsyncpgConnectArgs(TypedDict, total=False):
    ssl: ssl.SSLContext


def _ssl_connect_arg(sslmode: str) -> ssl.SSLContext | None:
    if sslmode in ("disable", "allow"):
        return None
    if sslmode in ("require", "prefer"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if sslmode == "verify-ca":
        # libpq verify-ca checks the CA chain only; verify-full adds the hostname.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        return ctx
    if sslmode in ("verify", "verify-full"):
        return ssl.create_default_context()
    raise ValueError(f"Unsupported sslmode={sslmode!r} in database URL")


def _query_param(query: dict[str, str | tuple[str, ...]], key: str) -> str | None:
    value = query.get(key)
    if value is None:
        return None
    if isinstance(value, tuple):
        return value[0] if value else None
    return value


def normalize_asyncpg_url(url: str) -> tuple[str, AsyncpgConnectArgs]:
    """Rewrite a libpq Postgres URL for asyncpg, which rejects libpq query params."""
    parsed = make_url(url)
    if parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+asyncpg")
    elif not parsed.drivername.startswith("postgresql"):
        raise ValueError("DB_URL must be a PostgreSQL connection string (postgresql://...)")

    sslmode = _query_param(dict(parsed.query), "sslmode")
    parsed = parsed.difference_update_query(["sslmode", "channel_binding"])

    connect_args: AsyncpgConnectArgs = {}
    if sslmode is not None:
        ssl_arg = _ssl_connect_arg(sslmode)
        if ssl_arg is not None:
            connect_args["ssl"] = ssl_arg
    return parsed.render_as_string(hide_password=False), connect_args


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


# `0.0.0.0`/`::` are bind addresses, so as wrong here as loopback. `HttpUrl.host` keeps
# IPv6 brackets, hence both spellings of ::1.
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
    def _reject_local_base_url_in_production(self) -> Self:
        """Left at the default, a deploy redirects clients to a login form on their own machine."""
        if self.app_env != AppEnv.PRODUCTION:
            return self
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
        return str(self.public_base_url).rstrip("/")


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
    """Where to reach the v3 REST API and how hard to lean on it.

    No credentials: each MCP client completes this service's own login form, and the username
    and password it submits are encrypted per user in Postgres. Spec: /v3/docs/json (public).
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="WITH_INTELLIGENCE_")

    base_url: str = "https://api.withintelligence.com"

    # Responses are auto-filtered to the licensed packages regardless; asking narrowly keeps a
    # hedge-fund question from paging through wealth records.
    asset_class_groups: tuple[AssetClassGroup, ...] = (AssetClassGroup.HFM,)

    default_timeout_seconds: float = Field(default=30.0, gt=0)

    # Every listing pages identically, so one size serves all of them.
    default_page_size: int = Field(default=50, ge=1, le=500)

    # Our own politeness bound: the vendor publishes no concurrency limit, only 429 on every path.
    max_concurrent_requests_per_user: int = Field(default=5, ge=1)

    max_retry_attempts: int = Field(default=3, ge=1)
    max_retry_wait_ms: int = Field(default=8_000, ge=0)


class DatabaseConfig(BaseSettings):
    """Either `url` / `DB_URL` (or Helm's `DATABASE_URL`), or all four discrete fields."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="DB_")

    url: PostgresDsn | None = None
    host: str | None = None
    port: int = 5432
    name: str | None = None
    user: str | None = None
    password: str | None = None
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
            self._connection_url, self._connect_args = normalize_asyncpg_url(str(self.url))
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
        self._connect_args = AsyncpgConnectArgs()
        return self

    @property
    def connection_url(self) -> str:
        return self._connection_url

    @property
    def connect_args(self) -> AsyncpgConnectArgs:
        return self._connect_args


class AuthConfig(BaseSettings):
    """Retention and sweep cadence for the OAuth rows this service issues.

    Without a periodic sweep four tables grow without bound, `oauth_tokens` fastest: every
    refresh rotation adds a row to the table `load_access_token` queries on every request.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="AUTH_")

    token_retention_days: int = Field(default=30, ge=1)

    # Client registration is open (RFC 7591), so every caller that ever registered leaves a row.
    # Comfortably longer than the pending-authorization TTL, so a client waiting on its user to
    # fill in the form cannot be swept mid-handshake.
    unused_client_retention_hours: float = Field(default=24.0, gt=0)

    cleanup_interval_hours: float = Field(default=6.0, gt=0)

    # Without this, the login form forwards any username/password pair to the vendor, which
    # makes it a credential-testing oracle for anyone who can start an OAuth flow.
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
    """Key used to encrypt stored With Intelligence credentials at rest."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WITH_INTELLIGENCE_MCP_"
    )

    encryption_key: SecretStr | None = None

    @model_validator(mode="after")
    def _require_encryption_key(self) -> Self:
        if self.encryption_key is None:
            raise ValueError("WITH_INTELLIGENCE_MCP_ENCRYPTION_KEY not set")
        return self
