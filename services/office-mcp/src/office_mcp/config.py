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

# libpq `sslmode` values asyncpg accepts. Only `verify` (libpq's alias for
# `verify-full`) is rewritten, because asyncpg does not accept the short spelling.
# Trap: verify-ca is a genuinely weaker mode. Never widen it to verify-full—that
# silently changes what the connection checks.
_ASYNCPG_SSLMODES = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})

# Trap: asyncpg forwards unknown params as server settings, causing Postgres errors.
# channel_binding is dropped to prevent startup failure.
_UNSUPPORTED_PARAMS = frozenset({"channel_binding"})


def asyncpg_dsn(url: str) -> str:
    """Convert a libpq PostgreSQL URL to asyncpg DSN format.

    Trap: `urlsplit` keeps `netloc` intact, so a percent-encoded password, a bracketed IPv6
    host, and a missing port all survive unchanged. A library that decodes and reassembles
    the parts would corrupt them. Only the scheme and the query change.
    There is no second connection shape that can negotiate TLS differently from the first.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql+asyncpg"):
        # postgres:// (libpq) and postgresql+asyncpg:// (SQLAlchemy) are not asyncpg schemes.
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
    """Convert libpq sslmode to asyncpg format."""
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
    """Case-insensitive names accepted by `unique_mcp.logging.configure_logging`."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ToolsPreset(StrEnum):
    """The named tool surfaces an operator may deploy — the names only, never their contents.

    Here rather than in `tools/` so that a misspelled `TOOLS_PRESET` is a startup error listing the
    values that would have worked, exactly as `AppEnv` and `LogLevel` above already are, and so the
    Helm chart's schema can carry the same `enum` and fail a `helm install` at validation instead of
    crash-looping a pod.

    Unlike `AppEnv` and `LogLevel`, an uppercase spelling is *not* accepted here, and the shared
    `enum` is why: the chart's schema matches these values exactly and JSON Schema has no
    case-insensitive enum, so a server taking `TOOLS_PRESET=TEAMS` would accept a value `helm
    install` rejects. Failing identically in both places beats absorbing the shift key.

    What each name expands to belongs to `tools/__init__.py`, the one module that knows which tools
    exist. Config is upstream of everything, so a config that knew the tool set would invert that
    dependency and be a second place the tool list lives — which is the duplication this whole
    feature is built to avoid. One test asserts the two sides agree in both directions.

    The names carry a product axis (`teams-`) from the start, because this connector grows to
    Outlook and SharePoint, and `outlook-*` names then join the table without re-cutting these. They
    are opaque table keys and not a grammar: nothing prefix-matches them and nothing expands them.
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

    # Externally-reachable URL of this service, used as OAuth issuer URL. HttpUrl so host
    # and scheme are parsed once and reused downstream.
    public_base_url: HttpUrl = HttpUrl("http://localhost:9544")

    # The Graph timeout budget, which `create_app` translates into the frozen `GraphSettings` the
    # transport is built from — `graph_client/` is told these and never reads them, so this is the
    # only place they exist. The defaults are sized for an interactive MCP client rather than for a
    # batch job; `GraphSettings` carries the reasoning for each one.
    #
    # What an operator is actually turning is the worst case of one tool call: a request timeout
    # times `graph_max_retries + 1` attempts, before any Retry-After wait, per Graph call — and a
    # paged walk makes several. Raising either past what the client on the other end will wait for
    # buys a slower failure and nothing else.
    #
    # Zero retries is allowed, and is a real choice: it gives up on the first 429 instead of
    # waiting out the Retry-After, which accrues quota without getting an answer. Zero timeouts are
    # refused, because httpx reads a timeout as a deadline and not as "unbounded" — `0` would time
    # every Graph call out before it left the process, which is not what anyone typing it means.
    #
    # TRAP: the retry ceiling is the SDK's, not a preference. `RetryHandlerOption.__init__` raises
    # `ValueError: MaxLimitExceeded. MaxRetries should not be more than $10` above
    # `MAX_MAX_RETRIES = 10` (kiota_http/middleware/options/retry_handler_option.py:12,38-41), and
    # it raises inside `create_graph_transport`, which runs inside `create_app`. Bounded here so
    # that `GRAPH_MAX_RETRIES=11` is a startup error naming the setting, rather than a crash-looping
    # pod carrying an SDK message that names no setting an operator has ever heard of.
    graph_request_timeout_seconds: float = Field(default=30.0, gt=0)
    graph_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    graph_max_retries: int = Field(default=3, ge=0, le=RetryHandlerOption.MAX_MAX_RETRIES)

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

    @model_validator(mode="after")
    def _reject_cleartext_base_url_in_production(self) -> Self:
        """Reject http URLs in production. The OAuth endpoints are published under this URL.

        Trap: nothing downstream fails closed. The auth provider reads the scheme, logs a
        warning for http, and then drops `Secure` from its OAuth consent cookies.
        """
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
        """Return `public_base_url` as a string without trailing slash for path joins.

        Trap: `HttpUrl` renders with a trailing slash, so joining a path onto it gives
        `https://host//authorize`. The OAuth discovery document re-parses the issuer on its
        own and restores the slash there.
        """
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
        """Read `TOOLS_ENABLED=get_me,list_chats` as the list it looks like.

        Trap: pydantic-settings JSON-decodes an env var whose field is a collection, and does it in
        the settings source *before* any validator here runs. `NoDecode` above is what turns that
        off, and it is deliberate rather than defensive: at the pinned version the decode failure is
        *tolerated* because the field is a union, so the raw string reaches this validator either
        way — but drop the `| None` and the same value becomes a `SettingsError` naming a field an
        operator has never heard of. The annotation is what makes the spelling every operator writes
        work on purpose instead of by accident.

        Blanks around the commas and a trailing one are absorbed; a value that names nothing at all
        is left as an empty tuple, for the validator below to refuse by name rather than to silently
        mean "no tools".
        """
        if not isinstance(value, str):
            return value
        return tuple(name.strip() for name in value.split(",") if name.strip())

    @model_validator(mode="after")
    def _require_exactly_one_selection(self) -> Self:
        """Refuse to start on any of the three ways the two variables say nothing usable.

        Every one of them is a deployment whose consent screen would not be what its operator
        believes, and none of them is fixable after the fact: a permission not requested at sign-in
        cannot be redeemed later, and one requested that the app registration does not carry fails
        the authorize hop for every user — with nothing in this server's logs either way.
        """
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


# Trap: these are Entra authority aliases that let any tenant sign in. AzureProvider derives one
# expected issuer from tenant_id (https://{authority}/{tenant_id}/v2.0) with no way to turn the
# check off. A real token's iss names the caller's tenant, so these fail all tokens identically
# with nothing in logs pointing at the tenant_id.
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
        """Accept DATABASE_URL (Helm alias) if url and discrete fields are not set.

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
        """DSN string for asyncpg.connect. The only database surface exposed."""
        return self._driver_dsn
