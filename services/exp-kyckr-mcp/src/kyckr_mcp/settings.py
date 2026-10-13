import os
from typing import ClassVar, Self

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def default_base_url(data: dict[str, object]) -> AnyHttpUrl:
    host = str(data["host"])
    if ":" in host:
        host = f"[{host}]"
    port = data["port"]
    assert isinstance(port, int)
    return AnyHttpUrl.build(scheme="http", host=host, port=port)


def default_allowed_origins(data: dict[str, object]) -> list[AnyHttpUrl]:
    if data["host"] in {"localhost", "127.0.0.1", "::1"}:
        return [AnyHttpUrl("http://localhost:6274")]
    return []


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    host: str = "127.0.0.1"
    port: int = Field(default=9542, ge=1, le=65535)
    log_level: str = "INFO"
    mcp_base_url: AnyHttpUrl = Field(default_factory=default_base_url)
    mcp_allowed_origins: list[AnyHttpUrl] = Field(default_factory=default_allowed_origins)
    mcp_api_key: SecretStr = Field(min_length=1)

    kyckr_api_key: SecretStr = Field(min_length=1)
    kyckr_api_url: AnyHttpUrl = AnyHttpUrl("https://test-api.kyckr.com/v2")
    kyckr_openapi_url: AnyHttpUrl = AnyHttpUrl(
        "https://developer.kyckr.com/openapi/company_v2.yaml"
    )
    kyckr_timeout_seconds: float = Field(default=30, gt=0, le=120)
    kyckr_default_customer_reference: str | None = None
    kyckr_default_contact_email: str | None = None

    @property
    def kyckr_base_url(self) -> str:
        return str(self.kyckr_api_url).rstrip("/")

    @property
    def mcp_path(self) -> str:
        return f"/{self.mcp_api_key.get_secret_value()}/mcp"

    @property
    def base_url(self) -> str:
        return str(self.mcp_base_url).rstrip("/")

    @property
    def allowed_hosts(self) -> list[str]:
        host = self.mcp_base_url.host
        assert host is not None
        return ["localhost", "127.0.0.1"] if host in LOCAL_HOSTS else [host]

    @model_validator(mode="after")
    def validate_mcp_url(self) -> Self:
        url = self.mcp_base_url
        if url.path not in {None, "", "/"} or url.query or url.fragment or url.username:
            raise ValueError("MCP_BASE_URL must be a bare origin")
        if url.host not in LOCAL_HOSTS and url.scheme != "https":
            raise ValueError("Remote MCP_BASE_URL requires HTTPS")
        return self
