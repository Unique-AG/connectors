from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_configs.config import shared_config


class RetrySettings(BaseSettings):
    """When a client sends a failed request again. A status in `statuses` is retried after its
    `Retry-After`, or an exponential backoff without one, as long as the wait stays within
    `max_wait_seconds`: a quota that resets in an hour is better reported than waited out. A
    `POST` or `PATCH` is sent again only on a 429, since another status may come after the write
    was applied.

    The prefix suits an MCP with one upstream. Another passes its own:
    `RetrySettings(_env_prefix="BILLING_RETRY_")`.
    """

    model_config: ClassVar[SettingsConfigDict] = shared_config("UPSTREAM_RETRY_")

    max_attempts: int = Field(default=5, ge=1)
    max_wait_seconds: float = Field(default=30, ge=0)
    statuses: frozenset[int] = frozenset({429, 503})
