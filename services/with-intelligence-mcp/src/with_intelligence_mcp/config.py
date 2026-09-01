"""One `BaseSettings` class per concern, read by the cached providers in `dependencies.py`.

Nothing here is read at import time: a provider constructs its config, so a test can set the
environment first and `teardown.close_singletons()` can drop what was read.

Auth and encryption settings are deliberately absent — this service has no login flow yet. They
arrive with `features/auth/`, together with the tables they configure.
"""

import os
import ssl
from enum import StrEnum
from importlib.metadata import version as pkg_version
from typing import ClassVar, Self, TypedDict, cast

from pydantic import Field, HttpUrl, PostgresDsn, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import URL, make_url

PKG_VERSION = pkg_version("with-intelligence-mcp")


class AsyncpgConnectArgs(TypedDict, total=False):
    ssl: ssl.SSLContext


def _ssl_connect_arg(sslmode: str) -> ssl.SSLContext | None:
    """Map a libpq `sslmode` value to an asyncpg `ssl` connect argument."""
    if sslmode in ("disable", "allow"):
        return None
    if sslmode in ("require", "prefer"):
        # Encrypt the connection but do not verify the server certificate.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if sslmode == "verify-ca":
        # Libpq verify-ca checks the CA chain only — not the hostname (that is verify-full).
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
    """Rewrite a libpq Postgres URL for SQLAlchemy/asyncpg.

    Helm injects `DATABASE_URL` with libpq query params (`sslmode=...`). asyncpg rejects
    those params, so strip them and return equivalent `connect_args` instead.
    """
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


# Hosts that can't be what an external MCP client reaches this service on. `0.0.0.0`/`::` are a
# bind address rather than a destination, so they're just as wrong as loopback here.
# `[::1]` is included because pydantic's `HttpUrl.host` keeps IPv6 brackets.
_NON_PUBLIC_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "::"})


class LogLevel(StrEnum):
    """Matches `unique_mcp.logging.configure_logging` accepted names (case-insensitive)."""

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

    # The externally-reachable URL of this service. With Intelligence has no OAuth, so this
    # service becomes the OAuth issuer for its MCP clients and this is the base every
    # discovery, `/authorize`, `/token` and login-form URL hangs off. Kept as a validated
    # `HttpUrl` rather than a string: both `host` and `scheme` are read downstream, and one
    # parse serving all of them is why nothing else re-parses it.
    public_base_url: HttpUrl = HttpUrl("http://localhost:9011")

    @model_validator(mode="after")
    def _reject_local_base_url_in_production(self) -> Self:
        """Fail fast when a production deploy never set `PUBLIC_BASE_URL`.

        Left at the default, this service would advertise a loopback issuer and redirect
        browsers to a login form on the client's own machine. Nothing errors server-side —
        clients just fail to connect for a reason nothing here reports.
        """
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
        """`public_base_url` as a string with no trailing slash, for joining paths onto.

        `HttpUrl` renders a bare origin with a trailing `/`, so interpolating a path straight
        onto it yields `https://host//login`.
        """
        return str(self.public_base_url).rstrip("/")


# Asset-class packages ("data solutions") the v3 API filters responses to, as accepted by the
# `asset_class_group` query parameter on every core endpoint. Unique's agreement covers With HFM
# (hedge funds) and With SFO (wealth / family office); the rest are listed so a deployment with a
# broader subscription is a configuration change rather than a code change.
class AssetClassGroup(StrEnum):
    HFM = "hfm"
    PEFI = "pefi"
    PCFI = "pcfi"
    REFI = "refi"
    CWI = "cwi"
    IWI = "iwi"
    SFO = "sfo"


class WithIntelligenceConfig(BaseSettings):
    """Where to reach the With Intelligence v3 REST API, and how hard to lean on it.

    Credentials are NOT configured here. With Intelligence issues a 1-hour access token over a
    30-day refresh token from `POST /v3/auth/sign-in` (username + password; the one-time
    passcode in their onboarding mail belongs to `POST /v3/auth/set-password`, which a user
    completes before ever reaching this service). Each connecting MCP client will complete this
    service's own hosted login form, and the resulting session is stored encrypted per user
    rather than shared across callers — see the auth feature, which lands next.

    Docs: https://withapi.readme.io/docs/getting-started, spec at
    https://api.withintelligence.com/v3/docs/json.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="WITH_INTELLIGENCE_")

    base_url: str = "https://api.withintelligence.com"

    # Which packages tool calls ask for. Responses are auto-filtered to what the account is
    # licensed for regardless, but asking narrowly keeps a hedge-fund question from paging
    # through wealth records to find its answer.
    asset_class_groups: tuple[AssetClassGroup, ...] = (AssetClassGroup.HFM,)

    default_timeout_seconds: float = Field(default=30.0, gt=0)

    # Every listing endpoint pages the same way (`page`, `page_size`, and a
    # `{pagination:{page,page_size,count,total}, results:[…]}` envelope), so one page size
    # serves all of them.
    default_page_size: int = Field(default=50, ge=1, le=500)

    # No published concurrency limit — unlike Backstop's hard 5-per-user cap, this is our own
    # politeness bound until a measured one replaces it. Every path documents 429.
    max_concurrent_requests_per_user: int = Field(default=5, ge=1)

    max_retry_attempts: int = Field(default=3, ge=1)
    max_retry_wait_ms: int = Field(default=8_000, ge=0)


class DatabaseConfig(BaseSettings):
    """Where this service stores OAuth clients/tokens and encrypted vendor sessions.

    Provide either `url` / `DB_URL` (or Helm's `DATABASE_URL` alias) **or** the discrete
    `host`/`name`/`user`/`password` fields. The discrete fields may be `None` when a URL is
    set — `_resolve_connection_url` only requires them when building a DSN from parts.
    """

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
        """SQLAlchemy/asyncpg URL after driver rewrite and libpq-param stripping."""
        return self._connection_url

    @property
    def connect_args(self) -> AsyncpgConnectArgs:
        """asyncpg connect args derived from libpq query params (e.g. sslmode)."""
        return self._connect_args
