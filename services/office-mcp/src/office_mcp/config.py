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

# libpq `sslmode` values asyncpg accepts. Only `verify` (libpq's alias for
# `verify-full`) is rewritten, because asyncpg does not accept the short spelling.
# Trap: verify-ca is a genuinely weaker mode. Never widen it to verify-full—that
# silently changes what the connection checks.
_ASYNCPG_SSLMODES = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})

# asyncpg forwards unrecognized query params as server settings, causing Postgres errors.
# `channel_binding` is dropped to prevent startup failure.
_UNSUPPORTED_PARAMS = frozenset({"channel_binding"})


def asyncpg_dsn(url: str) -> str:
    """Convert a libpq PostgreSQL URL to asyncpg DSN format. Rewrites scheme and sslmode values.

    Trap: `urlsplit` keeps `netloc` intact, so a percent-encoded password, a bracketed IPv6
    host, and a missing port all survive unchanged. A library that decodes and reassembles
    the parts would corrupt them. Only the scheme and the query change.
    There is no second connection shape that can negotiate TLS differently from the first.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql+asyncpg"):
        # `postgres://` (libpq) and `postgresql+asyncpg://` (SQLAlchemy) are not
        # recognized by asyncpg.
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
    """Convert libpq sslmode to asyncpg format. Rewrite `verify` to `verify-full`."""
    if sslmode == "verify":
        return "verify-full"
    if sslmode not in _ASYNCPG_SSLMODES:
        raise ValueError(f"Unsupported sslmode={sslmode!r} in database URL")
    return sslmode


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


# Hosts not reachable externally. `0.0.0.0` and `[::]` are bind addresses, not destinations.
# IPv6 entries keep their brackets because pydantic's `HttpUrl.host` keeps them too.
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

    # The externally-reachable URL of this service, used as the OAuth issuer URL.
    # Kept as `HttpUrl` so `host` and `scheme` are parsed once and reused downstream.
    public_base_url: HttpUrl = HttpUrl("http://localhost:9544")

    @model_validator(mode="before")
    @classmethod
    def _lowercase_log_level_and_app_env(cls, data: object) -> object:
        """Accept uppercase `LOG_LEVEL=INFO` and `APP_ENV=PRODUCTION` from operators.

        Trap: pydantic's `StrEnum` coercion is case-sensitive. Without this step, an
        uppercase value aborts startup instead.
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
        """Reject loopback URLs in production. Clients cannot reach localhost or 127.0.0.1.

        Trap: without this check, the server logs no error here. Clients simply fail to
        connect, with no signal anywhere that explains why.
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
        """Return `public_base_url` as a string without trailing slash for path joins.

        Trap: `HttpUrl` renders with a trailing slash, so joining a path onto it gives
        `https://host//authorize`. The OAuth discovery document re-parses the issuer on its
        own and restores the slash there.
        """
        return str(self.public_base_url).rstrip("/")


class DatabaseConfig(BaseSettings):
    """Hold PostgreSQL connection settings. Accept `DB_URL` or discrete fields.

    Expose `driver_dsn` only. Trap: deliberately no second, engine-shaped rendering.
    Two shapes are two places TLS can be negotiated differently.
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
        """Accept DATABASE_URL (Helm alias) if neither `url` nor discrete fields are set.

        Explicit args win. Trap: without this guard, an explicit `DatabaseConfig(host=...)`
        call would silently lose its arguments to the ambient environment instead.
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

        # Escape all reserved characters in user and password; unescaped delimiters reparse the DSN.
        # `quote`'s default leaves `/` unescaped, so `safe=""` forces full escaping here.
        userinfo = f"{quote(self.user, safe='')}:{quote(self.password, safe='')}"
        database = quote(self.name, safe="")
        # The host is written as given, so a bracketed IPv6 literal keeps its brackets.
        self._driver_dsn = f"postgresql://{userinfo}@{self.host}:{self.port}/{database}"
        return self

    @property
    def driver_dsn(self) -> str:
        """Return the DSN string for `asyncpg.connect`. The only database surface exposed."""
        return self._driver_dsn
