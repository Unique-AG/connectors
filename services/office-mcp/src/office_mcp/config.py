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
    SecretStr,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

PKG_VERSION = pkg_version("office-mcp")

# libpq `sslmode` values asyncpg accepts. Only `verify` (libpq's alias for
# `verify-full`) is rewritten.
# Trap: verify-ca is a genuinely weaker mode. Never widen it to verify-full—that
# silently changes what the connection checks.
_ASYNCPG_SSLMODES = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})

# asyncpg forwards unrecognized query params as server settings, causing Postgres errors.
# `channel_binding` is dropped to prevent startup failure.
_UNSUPPORTED_PARAMS = frozenset({"channel_binding"})


def asyncpg_dsn(url: str) -> str:
    """Convert a libpq PostgreSQL URL to asyncpg DSN format. Rewrites scheme and sslmode values.

    Trap: Use urllib.parse to preserve encoding and IPv6. There is no second connection
    shape that can negotiate TLS differently from the first.
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
        """Accept uppercase `LOG_LEVEL=INFO` and `APP_ENV=PRODUCTION` from operators."""
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
        """Reject loopback URLs in production. Clients cannot reach localhost or 127.0.0.1."""
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
        """Return `public_base_url` as a string without trailing slash for path joins."""
        return str(self.public_base_url).rstrip("/")


# Entra authority aliases that let any tenant sign in. `AzureProvider` derives exactly one
# expected issuer from `tenant_id` (`https://{authority}/{tenant_id}/v2.0`) and offers no way to
# turn that check off, but a real token's `iss` names the *caller's* tenant — so with one of these
# every token fails verification and every login fails identically, with nothing in the logs
# pointing at the tenant id.
_MULTI_TENANT_AUTHORITIES = frozenset({"common", "organizations", "consumers"})


class EntraConfig(BaseSettings):
    """The Microsoft Entra app registration this service authenticates users against.

    These three values are the whole of what FastMCP's `AzureProvider` needs from this service:
    it owns the authorization endpoint, PKCE, the redirect callback, token refresh, and the
    On-Behalf-Of exchange that turns a user's token into a Microsoft Graph one. `client_secret`
    is required here even though the provider itself allows omitting it, because On-Behalf-Of
    cannot be performed without one — and calling Graph as the signed-in user is the point.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="ENTRA_")

    tenant_id: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: SecretStr = Field(min_length=1)

    @model_validator(mode="after")
    def _reject_multi_tenant_authority(self) -> Self:
        if self.tenant_id.lower() in _MULTI_TENANT_AUTHORITIES:
            raise ValueError(
                f"ENTRA_TENANT_ID must name a single tenant, not {self.tenant_id!r}: the auth "
                + "provider validates every token against one issuer derived from this value, "
                + "so a multi-tenant authority rejects all of them. Use the tenant's ID."
            )
        return self


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

        Explicit args win.
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
        userinfo = f"{quote(self.user, safe='')}:{quote(self.password, safe='')}"
        database = quote(self.name, safe="")
        self._driver_dsn = f"postgresql://{userinfo}@{self.host}:{self.port}/{database}"
        return self

    @property
    def driver_dsn(self) -> str:
        """Return the DSN string for `asyncpg.connect`. The only database surface exposed."""
        return self._driver_dsn
