# mcp-scaffold-commit: 9a91a8864afe, timestamp: 2026-10-21T12:09:32+00:00

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

    api_key: SecretStr = Field(min_length=1)
    api_url: AnyHttpUrl = AnyHttpUrl("https://api.tiingo.com")
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    # Read from UPSTREAM_RETRY_*, with the defaults every MCP shares.
    retry: RetrySettings = Field(default_factory=RetrySettings)
