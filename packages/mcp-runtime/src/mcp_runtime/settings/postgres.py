import ssl
from pathlib import Path
from typing import ClassVar, Literal, Self, TypedDict, cast, get_args
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_runtime.settings.config import shared_config

SslMode = Literal["disable", "allow", "prefer", "require", "verify-ca", "verify", "verify-full"]


class AsyncpgConnectArgs(TypedDict, total=False):
    ssl: ssl.SSLContext | Literal["disable", "allow"]


class PostgresSettings(BaseSettings):
    """A Postgres connection for SQLAlchemy with asyncpg.

    Either a URL or the discrete fields. The base Helm chart injects `DATABASE_URL`, and
    `PG_DATABASE_SSL_MODE` beside it because a CloudNativePG URL carries no `sslmode`. An
    `sslmode` in the URL wins over it.
    """

    model_config: ClassVar[SettingsConfigDict] = shared_config("DB_")

    url: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("DB_URL", "DATABASE_URL")
    )
    host: str | None = None
    port: int = Field(default=5432, ge=1, le=65535)
    name: str | None = None
    user: str | None = None
    password: SecretStr | None = None
    ssl_mode: SslMode | None = Field(
        default=None, validation_alias=AliasChoices("PG_DATABASE_SSL_MODE", "DB_SSL_MODE")
    )
    # The chart mounts the CloudNativePG CA here when the cluster has one. Without the file, the
    # system trust store verifies the server, as a managed Postgres needs.
    ssl_root_cert: Path | None = None
    pool_size: int = Field(default=5, ge=1)
    max_overflow: int = Field(default=10, ge=0)

    @model_validator(mode="after")
    def _url_or_fields(self) -> Self:
        if self.url is not None:
            parts = urlsplit(self.url.get_secret_value())
            if not parts.scheme.startswith("postgres"):
                raise ValueError("DB_URL must be a PostgreSQL connection string (postgresql://...)")
            sslmode = dict(parse_qsl(parts.query)).get("sslmode")
            if sslmode is not None and sslmode not in get_args(SslMode):
                raise ValueError(f"Unsupported sslmode={sslmode} in DB_URL")
            return self
        fields = {"DB_HOST": self.host, "DB_NAME": self.name, "DB_USER": self.user}
        missing = [name for name, value in fields.items() if not value]
        if self.password is None:
            missing.append("DB_PASSWORD")
        if missing:
            raise ValueError(f"DB_URL not set; missing required fields: {', '.join(missing)}")
        return self

    @property
    def connection_url(self) -> str:
        """The URL for `create_async_engine`. asyncpg rejects libpq's `sslmode` and
        `channel_binding` parameters, so they are dropped here and passed as `connect_args`."""
        parts = urlsplit(self._raw_url)
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query)
            if key not in {"sslmode", "channel_binding"}
        ]
        return urlunsplit(parts._replace(scheme="postgresql+asyncpg", query=urlencode(query)))

    @property
    def connect_args(self) -> AsyncpgConnectArgs:
        sslmode = self._sslmode
        if sslmode is None:
            return {}
        cafile = (
            str(self.ssl_root_cert) if self.ssl_root_cert and self.ssl_root_cert.is_file() else None
        )
        match sslmode:
            case "disable" | "allow":
                return {"ssl": sslmode}
            case "prefer" | "require":
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                return {"ssl": context}
            case "verify-ca":
                context = ssl.create_default_context(cafile=cafile)
                context.check_hostname = False
                return {"ssl": context}
            case "verify" | "verify-full":
                return {"ssl": ssl.create_default_context(cafile=cafile)}

    @property
    def _raw_url(self) -> str:
        if self.url is not None:
            return self.url.get_secret_value()
        assert self.host and self.name and self.user and self.password, (
            "validated in _url_or_fields"
        )
        credentials = (
            f"{quote(self.user, safe='')}:{quote(self.password.get_secret_value(), safe='')}"
        )
        return f"postgresql://{credentials}@{self.host}:{self.port}/{quote(self.name, safe='')}"

    @property
    def _sslmode(self) -> SslMode | None:
        in_url = dict(parse_qsl(urlsplit(self._raw_url).query)).get("sslmode")
        return self.ssl_mode if in_url is None else cast(SslMode, in_url)
