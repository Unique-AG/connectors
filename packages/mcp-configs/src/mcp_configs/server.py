from typing import ClassVar, Self

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_configs.config import shared_config
from mcp_configs.hosts import LOCAL_HOSTS, url_host


def _default_base_url(data: dict[str, object]) -> AnyHttpUrl:
    port = data["port"]
    assert isinstance(port, int), "port is validated before base_url"
    return AnyHttpUrl.build(scheme="http", host=url_host(str(data["host"])), port=port)


def _default_allowed_origins(data: dict[str, object]) -> list[AnyHttpUrl]:
    # The MCP Inspector, so local debugging works without configuration.
    return [AnyHttpUrl("http://localhost:6274")] if data["host"] in LOCAL_HOSTS else []


class ServerSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config()

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    mcp_base_url: AnyHttpUrl = Field(default_factory=_default_base_url)
    mcp_allowed_origins: list[AnyHttpUrl] = Field(default_factory=_default_allowed_origins)

    @property
    def binds_to_loopback(self) -> bool:
        return self.host in LOCAL_HOSTS

    @property
    def base_url(self) -> str:
        return str(self.mcp_base_url).rstrip("/")

    @property
    def allowed_hosts(self) -> list[str]:
        host = self.mcp_base_url.host
        assert host is not None, "an http URL always has a host"
        return ["localhost", "127.0.0.1"] if host in LOCAL_HOSTS else [host]

    @property
    def allowed_origins(self) -> list[str]:
        return [str(url).rstrip("/") for url in self.mcp_allowed_origins]

    @model_validator(mode="after")
    def _bare_origin(self) -> Self:
        url = self.mcp_base_url
        if url.path not in {None, "", "/"} or url.query or url.fragment or url.username:
            raise ValueError("MCP_BASE_URL must be a bare origin")
        if url.host not in LOCAL_HOSTS and url.scheme != "https":
            raise ValueError("Remote MCP_BASE_URL requires HTTPS")
        return self
