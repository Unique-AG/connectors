import os
from enum import StrEnum
from importlib.metadata import version as pkg_version
from typing import ClassVar, Self, cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from pydantic import (
    Field,
    HttpUrl,
    PostgresDsn,
    PrivateAttr,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

PKG_VERSION = pkg_version("office-mcp")

# libpq `sslmode` values asyncpg understands verbatim. `verify` is libpq's own alias for
# `verify-full` and is the one value asyncpg rejects outright, so it — and only it — is rewritten.
# `verify-ca` is a genuinely weaker mode (CA chain, no hostname) that asyncpg supports, so
# widening it to `verify-full` would silently change what the connection checks.
_ASYNCPG_SSLMODES = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})

# libpq params asyncpg has no equivalent for, and does not merely ignore: any query key it does
# not recognise is passed through as a *server setting* in the startup packet, so leaving
# `channel_binding=require` in the DSN makes Postgres refuse the connection with
# `unrecognized configuration parameter "channel_binding"`. Dropped here instead.
_UNSUPPORTED_PARAMS = frozenset({"channel_binding"})


def asyncpg_dsn(url: str) -> str:
    """Rewrite a libpq Postgres URL into the DSN asyncpg itself accepts.

    One DSN is the whole database surface of this service: the readiness probe and (once it
    lands) FastMCP's OAuth store both hand this exact string to `asyncpg.connect`, so there is
    no second connection shape that can negotiate TLS differently from the first.

    Built on `urllib.parse` rather than a URL library that reassembles from decoded parts:
    `urlsplit` leaves `netloc` — userinfo, host and port together — as written, so a
    percent-encoded password (`p%40ss`), a bracketed IPv6 host and an absent port all survive
    verbatim. Only the scheme and the query are rewritten.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql+asyncpg"):
        # `postgres://` is the libpq short form (Heroku/Azure and many operator-generated
        # secrets emit it) and `postgresql+asyncpg://` is SQLAlchemy's driver-qualified form
        # (what a Helm chart or a copied connection string may carry). asyncpg rejects both.
        scheme = "postgresql"
    elif scheme != "postgresql":
        raise ValueError("DB_URL must be a PostgreSQL connection string (postgresql://...)")

    query = urlencode(
        [
            (key, _asyncpg_sslmode(value) if key == "sslmode" else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key not in _UNSUPPORTED_PARAMS
        ]
    )
    return urlunsplit((scheme, parts.netloc, parts.path, query, parts.fragment))


def _asyncpg_sslmode(sslmode: str) -> str:
    """The asyncpg spelling of a libpq `sslmode`. Only `verify` differs."""
    if sslmode == "verify":
        return "verify-full"
    if sslmode not in _ASYNCPG_SSLMODES:
        raise ValueError(f"Unsupported sslmode={sslmode!r} in database URL")
    return sslmode


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


# Hosts that can't be what an external MCP client reaches this service on. `0.0.0.0`/`[::]` are a
# bind address rather than a destination, so they're just as wrong as loopback here.
# The IPv6 entries are bracketed because pydantic's `HttpUrl.host` keeps IPv6 brackets.
_NON_PUBLIC_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "[::]"})


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
    port: int = Field(default=9544, ge=0, le=65535)
    log_level: LogLevel = LogLevel.INFO

    # The externally-reachable URL of this service — used as the OAuth issuer/base URL
    # (discovery metadata, /authorize, /token, and the redirect endpoints all hang off it).
    # The local default is only usable in development; `_reject_local_base_url_in_production`
    # below enforces that.
    # Kept as the validated `HttpUrl` rather than a string: `host` and `scheme` are both read
    # downstream (here, and by the auth layer once it lands), and one parse serving all of them
    # is why none of those places re-parse it.
    public_base_url: HttpUrl = HttpUrl("http://localhost:9544")

    @model_validator(mode="before")
    @classmethod
    def _lowercase_log_level_and_app_env(cls, data: object) -> object:
        """Lowercase `log_level`/`app_env` before enum coercion.

        Pydantic's `StrEnum` coercion is case-sensitive, but `LOG_LEVEL=INFO` — the canonical
        spelling, and what `unique_mcp.logging.configure_logging` itself normalises — is a
        reasonable thing for an operator to set. Without this, it aborts startup instead.
        """
        if not isinstance(data, dict):
            return data
        values = cast(dict[str, object], data)
        for field in ("log_level", "app_env"):
            value = values.get(field)
            if isinstance(value, str):
                values = {**values, field: value.lower()}
        return values

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
    set — `_resolve_driver_dsn` only requires them when building a DSN from parts.

    Exactly one thing comes out: `driver_dsn`, the string every caller passes to
    `asyncpg.connect`. There is deliberately no second, engine-shaped rendering of the same
    settings — two shapes are two places TLS can be negotiated differently.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="DB_")

    url: PostgresDsn | None = None
    host: str | None = None
    port: int = 5432
    name: str | None = None
    user: str | None = None
    password: str | None = None
    _driver_dsn: str = PrivateAttr(default="")

    @model_validator(mode="before")
    @classmethod
    def accept_database_url(cls, data: object) -> object:
        """Accept DATABASE_URL (injected by the base Helm chart) as an alias for DB_URL.

        Only falls back to the ambient DATABASE_URL when neither `url` nor any discrete field
        was supplied. Without that guard, this read applied on every construction path — not
        just env-sourced ones — so an explicit `DatabaseConfig(host=..., name=..., ...)` call
        would have its arguments silently discarded in favor of whatever happened to be in the
        environment. Explicit arguments must win over the environment.
        """
        if not isinstance(data, dict):
            return data
        values = cast(dict[str, object], data)
        if values.get("url") is not None:
            return values
        if any(values.get(field) is not None for field in ("host", "name", "user", "password")):
            return values
        database_url = os.environ.get("DATABASE_URL")
        if database_url:
            return {**values, "url": database_url}
        return values

    @model_validator(mode="after")
    def _resolve_driver_dsn(self) -> Self:
        if self.url is not None:
            self._driver_dsn = asyncpg_dsn(str(self.url))
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

        assert self.user is not None and self.password is not None and self.name is not None, (
            "the missing-field check above must leave every discrete part set"
        )

        # `safe=""` because `quote`'s default leaves `/` (and more) unescaped, and each of these
        # is a single URL component: anything reserved inside one has to be encoded or the DSN
        # reparses with the delimiter in the wrong place. The host is interpolated as written,
        # so a bracketed IPv6 literal keeps its brackets.
        userinfo = f"{quote(self.user, safe='')}:{quote(self.password, safe='')}"
        database = quote(self.name, safe="")
        self._driver_dsn = f"postgresql://{userinfo}@{self.host}:{self.port}/{database}"
        return self

    @property
    def driver_dsn(self) -> str:
        """The DSN to hand `asyncpg.connect`. The only database surface this config exposes."""
        return self._driver_dsn
