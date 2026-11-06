# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

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

    # Service-account id, a short id rather than a UUID. UPSTREAM_API_SECRET is its
    # password, a UUID.
    api_key: SecretStr = Field(min_length=1)
    api_secret: SecretStr = Field(min_length=1)
    api_url: AnyHttpUrl = AnyHttpUrl("https://api.risk.lseg.com/screening/v3")
    token_url: AnyHttpUrl = AnyHttpUrl("https://api.risk.lseg.com/auth/oauth2/v1/token")
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    # Read from UPSTREAM_RETRY_*, with the defaults every MCP shares.
    retry: RetrySettings = Field(default_factory=RetrySettings)
