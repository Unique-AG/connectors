# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from typing import ClassVar

from mcp_configs import RetrySettings
from mcp_configs import shared_config
from pydantic import AnyHttpUrl
from pydantic import Field
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class UpstreamSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config("UPSTREAM_")

    # Polixis wants both on every request: a client-credentials token from its Keycloak realm
    # and the API key in `x-api-key`.
    client_id: SecretStr = Field(min_length=1)
    client_secret: SecretStr = Field(min_length=1)
    api_key: SecretStr = Field(min_length=1)
    api_url: AnyHttpUrl = AnyHttpUrl("https://api-polixis.polixis.com")
    token_url: AnyHttpUrl = AnyHttpUrl(
        "https://auth.polixis.com/realms/plx-prod/protocol/openid-connect/token"
    )
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    # Read from UPSTREAM_RETRY_*, with the defaults every MCP shares.
    retry: RetrySettings = Field(default_factory=RetrySettings)
