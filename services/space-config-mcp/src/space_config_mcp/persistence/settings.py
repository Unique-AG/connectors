from typing import ClassVar

from mcp_configs import shared_config
from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class PersistenceSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config("SPACE_CONFIG_MCP_")

    history_folder: str = Field(default="_space-config-history")
