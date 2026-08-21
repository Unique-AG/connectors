import os
from enum import StrEnum
from importlib.metadata import version as pkg_version
from typing import Annotated, ClassVar, Self, cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from kiota_http.middleware.options.retry_handler_option import RetryHandlerOption
from pydantic import (
    Field,
    HttpUrl,
    PostgresDsn,
    PrivateAttr,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PKG_VERSION = pkg_version("office-mcp")

# libpq `sslmode` values asyncpg accepts; `verify` is rewritten because asyncpg rejects the short
# spelling. Trap: `verify-ca` is a genuinely weaker mode. Never widen it to `verify-full` — the
# wider mode silently changes what the connection checks.
_ASYNCPG_SSLMODES = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})

# Trap: asyncpg forwards unknown params as server settings, so `channel_binding` fails startup.
_UNSUPPORTED_PARAMS = frozenset({"channel_binding"})


def asyncpg_dsn(url: str) -> str:
    """Trap: `urlsplit` keeps `netloc` intact, so a percent-encoded password, a bracketed IPv6 host
    and a missing port all survive. A library that decodes and reassembles the parts corrupts them.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql+asyncpg"):
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
    if sslmode == "verify":
        return "verify-full"
    if sslmode not in _ASYNCPG_SSLMODES:
        raise ValueError(f"Unsupported sslmode={sslmode!r} in database URL")
    return sslmode


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


# Bracketed spellings are listed too, because pydantic's `HttpUrl.host` keeps the brackets.
_NON_PUBLIC_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "[::]"})


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ToolsPreset(StrEnum):
    """The named tool surfaces an operator may deploy; `tools/__init__.py` maps each to its tools.

    Trap: unlike `AppEnv` and `LogLevel`, an uppercase spelling is not accepted, because the Helm
    chart's schema carries these same values as a JSON Schema `enum`, which has no
    case-insensitive form.
    """

    TEAMS = "teams"
    TEAMS_CHAT = "teams-chat"
    TEAMS_MESSAGES = "teams-messages"
    TEAMS_CHANNELS = "teams-channels"
    TEAMS_TRANSCRIPTS = "teams-transcripts"
    TEAMS_RECORDINGS = "teams-recordings"
    TEAMS_MEETINGS = "teams-meetings"


class AppConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict()

    app_env: AppEnv = AppEnv.PRODUCTION
    version: str = PKG_VERSION
    port: int = Field(default=9544, ge=0, le=65535)
    log_level: LogLevel = LogLevel.INFO

    public_base_url: HttpUrl = HttpUrl("http://localhost:9544")

    # Worst case of one tool call: the request timeout times `graph_max_retries + 1` attempts,
    # before any Retry-After wait, per Graph call, and a paged walk makes several.
    #
    # Zero timeouts are refused: httpx reads a timeout as a deadline and not as "unbounded", so `0`
    # would time every Graph call out before it left the process.
    #
    # TRAP: the retry ceiling is the SDK's. `RetryHandlerOption.__init__` raises `ValueError:
    # MaxLimitExceeded. MaxRetries should not be more than $10` above `MAX_MAX_RETRIES = 10`
    # (kiota_http/middleware/options/retry_handler_option.py:12,38-41), from inside
    # `create_graph_transport` and so inside `create_app`. Bounded here so that
    # `GRAPH_MAX_RETRIES=11` is a startup error naming the setting.
    graph_request_timeout_seconds: float = Field(default=30.0, gt=0)
    graph_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    graph_max_retries: int = Field(default=3, ge=0, le=RetryHandlerOption.MAX_MAX_RETRIES)

    # Named fields rather than a model validator over the whole dict: pydantic resolves the names
    # at class-definition time, so renaming a field here becomes an import error instead of a
    # validator that silently stops firing.
    @field_validator("log_level", "app_env", mode="before")
    @classmethod
    def _lowercase(cls, value: object) -> object:
        """Accept uppercase `LOG_LEVEL=INFO` and `APP_ENV=PRODUCTION` from operators.

        Trap: pydantic's `StrEnum` coercion is case-sensitive, so without this step an uppercase
        value aborts startup instead.
        """
        return value.lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _reject_local_base_url_in_production(self) -> Self:
        """Trap: without this the server logs nothing and clients simply fail to connect."""
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

    @model_validator(mode="after")
    def _reject_cleartext_base_url_in_production(self) -> Self:
        """Trap: nothing downstream fails closed — the auth provider logs a warning for http and
        then drops `Secure` from its OAuth consent cookies."""
        if self.app_env != AppEnv.PRODUCTION:
            return self
        if self.public_base_url.scheme != "https":
            raise ValueError(
                "PUBLIC_BASE_URL must use https in "
                + f"{AppEnv.PRODUCTION} (got {self.public_base_url}); the OAuth discovery, "
                + "authorize and token endpoints are published under it"
            )
        return self

    @property
    def issuer(self) -> str:
        """Trap: `HttpUrl` renders with a trailing slash, so joining a path onto it gives
        `https://host//authorize`."""
        return str(self.public_base_url).rstrip("/")


class SurfaceConfig(BaseSettings):
    """Which tools this deployment runs, and so what every user is asked to consent to at sign-in.

    Exactly one of the two is a selection. Both set is an error naming which to remove rather than a
    precedence rule nobody would remember; neither set is an error too, because **there is no
    default**: a default of "every tool" would make the widest consent screen the thing an operator
    gets by not choosing, which is the whole of what this knob exists to stop. `TOOLS_PRESET=teams`
    keeps "everything" a one-word but chosen value.

    Narrowing a live deployment costs nothing. Widening one adds a permission to the authorize
    request, so every signed-in user meets AADSTS65001 on the new tool until they sign in again —
    the same footnote the README carries for rotating the client secret.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict()

    tools_preset: ToolsPreset | None = None
    tools_enabled: Annotated[tuple[str, ...] | None, NoDecode] = None

    @field_validator("tools_enabled", mode="before")
    @classmethod
    def _split_the_list_an_operator_writes(cls, value: object) -> object:
        """Trap: pydantic-settings JSON-decodes an env var whose field is a collection, before any
        validator here runs; `NoDecode` turns that off. The `| None` is load-bearing too: at the
        pinned version the decode failure is tolerated only because the field is a union.
        """
        if not isinstance(value, str):
            return value
        return tuple(name.strip() for name in value.split(",") if name.strip())

    @model_validator(mode="after")
    def _require_exactly_one_selection(self) -> Self:
        """None of the three is fixable after the fact: a permission not requested at sign-in
        cannot be redeemed later, and neither failure shows up in this server's logs."""
        if self.tools_preset is not None and self.tools_enabled is not None:
            raise ValueError(
                "TOOLS_PRESET and TOOLS_ENABLED are alternatives and both are set: remove one. "
                + f"Keep TOOLS_PRESET={self.tools_preset} for that named surface, or keep "
                + "TOOLS_ENABLED to name the tools yourself"
            )
        if self.tools_enabled is not None and not self.tools_enabled:
            raise ValueError(
                "TOOLS_ENABLED is set but names no tool. Give it a comma-separated list of tool "
                + f"names, or set TOOLS_PRESET to one of: {', '.join(ToolsPreset)}"
            )
        if self.tools_preset is None and self.tools_enabled is None:
            raise ValueError(
                "this deployment has no tool surface: set TOOLS_PRESET to one of "
                + f"{', '.join(ToolsPreset)}, or TOOLS_ENABLED to a comma-separated list of tool "
                + "names. There is deliberately no default, because the tools enabled decide which "
                + "delegated Graph permissions every user of this connector consents to"
            )
        return self


# Trap: Entra authority aliases. AzureProvider derives one expected issuer from tenant_id
# (https://{authority}/{tenant_id}/v2.0) with no way to turn the check off, and a real token's `iss`
# names the caller's tenant — so these reject every token, with nothing in logs naming tenant_id.
_MULTI_TENANT_AUTHORITIES = frozenset({"common", "organizations", "consumers"})


class EntraConfig(BaseSettings):
    """Microsoft Entra app registration for this service.

    AzureProvider owns the authorization endpoint, PKCE, redirect callback, token refresh, and
    On-Behalf-Of exchange. client_secret is required here (though the provider allows omitting
    it) because On-Behalf-Of cannot be done without one — and calling Graph as the signed-in
    user is the point.
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
    """PostgreSQL connection settings. Accept DB_URL or discrete fields.

    Expose driver_dsn only. Trap: no second engine-shaped rendering. Two shapes negotiate TLS
    differently.
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
        """Accept DATABASE_URL (the base Helm chart's alias) as a last resort.

        Any source that sets `url`, or any one of `host`/`name`/`user`/`password`, suppresses the
        fallback entirely — the env var is read only when nothing else names a database. Trap:
        without that guard, an explicit `DatabaseConfig(host=...)` call would silently lose its
        arguments to the ambient environment instead.
        """
        if not isinstance(data, dict):
            return data
        values = cast("dict[str, object]", data)
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

        # An unescaped delimiter reparses the DSN, and `quote`'s default leaves `/` alone, so
        # `safe=""` is what forces full escaping.
        userinfo = f"{quote(self.user, safe='')}:{quote(self.password, safe='')}"
        database = quote(self.name, safe="")
        # The host is written as given, so a bracketed IPv6 literal keeps its brackets.
        self._driver_dsn = f"postgresql://{userinfo}@{self.host}:{self.port}/{database}"
        return self

    @property
    def driver_dsn(self) -> str:
        return self._driver_dsn
