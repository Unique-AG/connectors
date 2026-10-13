import os
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Self

from pydantic import AnyHttpUrl, Field, SecretStr, UrlConstraints, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

HTTPSUrl = Annotated[AnyHttpUrl, UrlConstraints(allowed_schemes=["https"])]
SigningKey = Annotated[SecretStr, Field(min_length=32)]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


class PythonEnv(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AuthMode(StrEnum):
    ZITADEL = "zitadel"
    NONE = "none"


def default_base_url(data: dict[str, Any]) -> AnyHttpUrl:
    """http://HOST:PORT from the validated fields."""
    host = f"[{data['host']}]" if ":" in data["host"] else data["host"]
    return AnyHttpUrl.build(scheme="http", host=host, port=data["port"])


def default_allowed_origins(data: dict[str, Any]) -> list[AnyHttpUrl]:
    """The MCP Inspector in development, no browser origin otherwise."""
    inspector = [AnyHttpUrl("http://localhost:6274")]
    return inspector if data["python_env"] == PythonEnv.DEVELOPMENT else []


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    host: str = Field(default="127.0.0.1", description="Bind address")
    port: int = Field(default=8741, ge=1, le=65535)
    python_env: PythonEnv = PythonEnv.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    mcp_base_url: AnyHttpUrl = Field(
        default_factory=default_base_url,
        description="Public service origin, without /mcp (default: http://HOST:PORT)",
    )
    mcp_auth_mode: AuthMode = Field(
        default=AuthMode.ZITADEL, description="none is restricted to local development"
    )
    mcp_allowed_origins: list[AnyHttpUrl] = Field(
        default_factory=default_allowed_origins,
        description="Browser origins allowed to call /mcp (default: the Inspector in development)",
    )
    mcp_jwt_signing_key: SigningKey | None = Field(
        default=None, description="Stable random signing secret; required in Zitadel mode"
    )

    zitadel_issuer_url: HTTPSUrl | None = Field(default=None, description="Zitadel issuer base URL")
    zitadel_client_id: Annotated[str, Field(min_length=1)] | None = None
    zitadel_org_id: str | None = Field(
        default=None, description="Optionally restrict login to members of this organization"
    )

    tiingo_api_key: SecretStr = Field(min_length=1)
    tiingo_api_url: HTTPSUrl = AnyHttpUrl("https://api.tiingo.com")
    tiingo_timeout_seconds: float = Field(default=30, gt=0, le=120)

    @property
    def base_url(self) -> str:
        return str(self.mcp_base_url).rstrip("/")

    @property
    def allowed_hosts(self) -> list[str]:
        # A local server is reachable by either loopback name, whichever URL a client was given.
        host = self.mcp_base_url.host
        assert host is not None
        return ["localhost", "127.0.0.1"] if host in LOCAL_HOSTS else [host]

    @model_validator(mode="after")
    def validate_security(self) -> Self:
        url = self.mcp_base_url
        local = url.host in LOCAL_HOSTS
        production = self.python_env == PythonEnv.PRODUCTION
        if url.path not in {None, "", "/"} or url.query or url.fragment or url.username:
            raise ValueError("MCP_BASE_URL must be a bare origin")
        if (production or not local) and url.scheme != "https":
            raise ValueError("Remote and production MCP_BASE_URL require HTTPS")
        if self.mcp_auth_mode == AuthMode.NONE:
            if production or self.host not in {"127.0.0.1", "::1"}:
                raise ValueError(
                    "Unauthenticated mode is restricted to non-production, loopback-bound servers"
                )
        else:
            if not all((self.zitadel_issuer_url, self.zitadel_client_id, self.mcp_jwt_signing_key)):
                raise ValueError("Zitadel issuer, client ID, and MCP_JWT_SIGNING_KEY are required")
        return self
