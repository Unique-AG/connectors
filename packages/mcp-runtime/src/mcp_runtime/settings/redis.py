from typing import ClassVar

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_runtime.settings.config import shared_config


class RedisSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config()

    url: SecretStr = Field(min_length=1, validation_alias=AliasChoices("REDIS_URL"))
