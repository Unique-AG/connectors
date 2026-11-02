from typing import ClassVar

from mcp_configs import shared_config
from pydantic import Field
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class UpstreamSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config("SPACE_CONFIG_MCP_")

    unique_api_key: SecretStr = Field(min_length=1)
    unique_app_id: str = Field(min_length=1)
    unique_api_base: str = Field(default="https://gateway.unique.app/public/chat-gen2")
    service_user_id: str | None = Field(default=None)
    service_company_id: str | None = Field(default=None)
