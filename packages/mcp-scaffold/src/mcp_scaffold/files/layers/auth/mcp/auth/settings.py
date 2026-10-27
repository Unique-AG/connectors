from typing import ClassVar

from mcp_configs import shared_config
from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config("MCP_AUTH_")

    # A username is refused for the rest of the window once this many sign-ins failed in it.
    max_failed_sign_ins: int = Field(default=10, ge=1)
    failed_sign_in_window_minutes: int = Field(default=15, ge=1)
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=30, ge=1)
