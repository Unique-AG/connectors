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

PKG_VERSION = pkg_version("office-365-mcp")

_ASYNCPG_SSLMODES = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})

_UNSUPPORTED_PARAMS = frozenset({"channel_binding"})


def asyncpg_dsn(url: str) -> str:
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


_NON_PUBLIC_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "[::]"})


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ToolsPreset(StrEnum):
    TEAMS = "teams"
    TEAMS_CHAT = "teams-chat"
    TEAMS_MESSAGES = "teams-messages"
    TEAMS_CHANNELS = "teams-channels"
    TEAMS_TRANSCRIPTS = "teams-transcripts"
    TEAMS_RECORDINGS = "teams-recordings"
    TEAMS_MEETINGS = "teams-meetings"
    TEAMS_WRITE = "teams-write"
    OUTLOOK_READ = "outlook-read"
    OUTLOOK_MAILBOX = "outlook-mailbox"
    OUTLOOK_WRITE = "outlook-write"
    OUTLOOK_SEND = "outlook-send"
    OUTLOOK_AUTOMATE = "outlook-automate"
    OUTLOOK_CALENDAR = "outlook-calendar"
    OUTLOOK_CALENDAR_WRITE = "outlook-calendar-write"
    OUTLOOK_CALENDAR_DELEGATE = "outlook-calendar-delegate"
    SHAREPOINT_SEARCH = "sharepoint-search"
    SHAREPOINT_READ = "sharepoint-read"
    ONENOTE_READ = "onenote-read"
    ONENOTE_WRITE = "onenote-write"
    ONENOTE_DELETE = "onenote-delete"


class AppConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict()

    app_env: AppEnv = AppEnv.PRODUCTION
    version: str = PKG_VERSION
    port: int = Field(default=9544, ge=0, le=65535)
    log_level: LogLevel = LogLevel.INFO

    public_base_url: HttpUrl = HttpUrl("http://localhost:9544")

    graph_request_timeout_seconds: float = Field(default=30.0, gt=0)
    graph_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    graph_max_retries: int = Field(default=3, ge=0, le=RetryHandlerOption.MAX_MAX_RETRIES)

    @field_validator("log_level", "app_env", mode="before")
    @classmethod
    def _lowercase(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _reject_local_base_url_in_production(self) -> Self:
        if self.app_env != AppEnv.PRODUCTION:
            return self
        host = self.public_base_url.host
        assert host is not None, f"validated HttpUrl without a host: {self.public_base_url}"
        if host in _NON_PUBLIC_HOSTS:
            raise ValueError(
                "PUBLIC_BASE_URL must be this service's externally-reachable URL in "
                + f"{AppEnv.PRODUCTION} (got {self.public_base_url}). It is the OAuth issuer "
                + "clients are redirected to."
            )
        return self

    @model_validator(mode="after")
    def _reject_cleartext_base_url_in_production(self) -> Self:
        if self.app_env != AppEnv.PRODUCTION:
            return self
        if self.public_base_url.scheme != "https":
            raise ValueError(
                "PUBLIC_BASE_URL must use https in "
                + f"{AppEnv.PRODUCTION} (got {self.public_base_url}). The OAuth discovery, "
                + "authorize and token endpoints are published under it."
            )
        return self

    @property
    def issuer(self) -> str:
        return str(self.public_base_url).rstrip("/")


class SurfaceConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict()

    tools_preset: ToolsPreset | None = None
    tools_enabled: Annotated[tuple[str, ...] | None, NoDecode] = None

    @field_validator("tools_enabled", mode="before")
    @classmethod
    def _split_the_list_an_operator_writes(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return tuple(name.strip() for name in value.split(",") if name.strip())

    @model_validator(mode="after")
    def _require_exactly_one_selection(self) -> Self:
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


ORGANIZATIONS = "organizations"

_PERSONAL_ACCOUNT_AUTHORITIES = frozenset({"common", "consumers"})

_NAMED_AUTHORITIES = _PERSONAL_ACCOUNT_AUTHORITIES | {ORGANIZATIONS}


class EntraConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="ENTRA_")

    tenant_id: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: SecretStr = Field(min_length=1)

    @field_validator("tenant_id", mode="before")
    @classmethod
    def _lowercase_a_named_authority(cls, value: object) -> object:
        if isinstance(value, str) and value.lower() in _NAMED_AUTHORITIES:
            return value.lower()
        return value

    @model_validator(mode="after")
    def _reject_personal_account_authorities(self) -> Self:
        if self.tenant_id in _PERSONAL_ACCOUNT_AUTHORITIES:
            raise ValueError(
                f"ENTRA_TENANT_ID must name one tenant or be {ORGANIZATIONS!r}, not "
                + f"{self.tenant_id!r}: that authority admits personal Microsoft accounts, which "
                + "have no Microsoft 365 mailbox or Teams for any tool here to read"
            )
        return self

    @property
    def multi_tenant(self) -> bool:
        return self.tenant_id == ORGANIZATIONS


class DatabaseConfig(BaseSettings):
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
            raise ValueError(f"DB_URL not set. Missing required fields: {', '.join(missing)}")

        assert self.user is not None and self.password is not None and self.name is not None, (
            "the missing-field check above must leave every discrete part set"
        )

        userinfo = f"{quote(self.user, safe='')}:{quote(self.password, safe='')}"
        database = quote(self.name, safe="")
        self._driver_dsn = f"postgresql://{userinfo}@{self.host}:{self.port}/{database}"
        return self

    @property
    def driver_dsn(self) -> str:
        return self._driver_dsn
