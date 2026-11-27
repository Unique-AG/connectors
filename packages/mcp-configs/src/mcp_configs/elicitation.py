from typing import Annotated, ClassVar

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_configs.config import shared_config


class ElicitationSettings(BaseSettings):
    """Answer timeout (protocols up to 2025-11-25) and the keys that seal `request_state`."""

    model_config: ClassVar[SettingsConfigDict] = shared_config("ELICITATION_")

    timeout_before_cancel_seconds: float = Field(default=120, gt=0)
    request_state_keys: list[Annotated[SecretStr, Field(min_length=32)]] = Field(
        default_factory=list
    )
