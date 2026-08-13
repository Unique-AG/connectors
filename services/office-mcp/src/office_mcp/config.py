import os
import ssl
from enum import StrEnum
from importlib.metadata import version as pkg_version
from typing import ClassVar, Self, TypedDict, cast

from pydantic import (
    Field,
    HttpUrl,
    PostgresDsn,
    PrivateAttr,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import URL, make_url

PKG_VERSION = pkg_version("office-mcp")


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
    port: int = Field(default=9010, ge=0, le=65535)
    log_level: LogLevel = LogLevel.INFO

    # The externally-reachable URL of this service — used as the OAuth issuer/base URL
    # (discovery metadata, /authorize, /token, and the redirect endpoints all hang off it).
    # The local default is only usable in development; `_reject_local_base_url_in_production`
    # below enforces that.
    # Kept as the validated `HttpUrl` rather than a string: `host` and `scheme` are both read
    # downstream (here, and by the auth layer once it lands), and one parse serving all of them
    # is why none of those places re-parse it.
    public_base_url: HttpUrl = HttpUrl("http://localhost:9010")

    @model_validator(mode="after")
    def _reject_local_base_url_in_production(self) -> Self:
        """Fail fast when a production deploy never set `PUBLIC_BASE_URL`.

        Left at the default, this service advertises a loopback issuer in its OAuth discovery
        metadata and redirects browsers to a login form on the client's own machine. Nothing
        errors server-side — clients just fail to connect for a reason nothing here reports. So
        it's rejected at startup, the same way a missing encryption key is.
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
        onto it yields `https://host//authorize`. Callers build redirects that way, so the slash
        is stripped once here rather than at each call site. Note the OAuth discovery document is
        not this value: the MCP SDK re-parses the issuer into an `AnyHttpUrl` and advertises it
        with the slash restored.
        """
        return str(self.public_base_url).rstrip("/")


class DatabaseConfig(BaseSettings):
    """Where office-mcp stores its state.

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
