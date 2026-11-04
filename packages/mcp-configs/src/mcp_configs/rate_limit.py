from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_configs.config import shared_config


class RateLimitSettings(BaseSettings):
    """How many tool calls one user may make within a sliding window. The count is held in each
    server process, so with several replicas a user can make that many calls on each of them.
    A limit of 0 turns the limit off."""

    model_config: ClassVar[SettingsConfigDict] = shared_config("MCP_RATE_LIMIT_")

    tool_calls_per_window: int = Field(default=60, ge=0)
    window_seconds: float = Field(default=60, gt=0)
