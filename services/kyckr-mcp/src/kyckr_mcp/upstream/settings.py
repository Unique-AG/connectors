# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

from typing import ClassVar

from mcp_configs import RetrySettings
from mcp_configs import shared_config
from pydantic import AnyHttpUrl
from pydantic import EmailStr
from pydantic import Field
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class KyckrRetrySettings(RetrySettings):
    # A 503 may come after Kyckr charged a paid read, so only a turned-away request is retried.
    statuses: frozenset[int] = frozenset({429})


class UpstreamSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config("UPSTREAM_")

    api_key: SecretStr = Field(min_length=1)
    api_url: AnyHttpUrl = AnyHttpUrl("https://test-api.kyckr.com/v2")
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    default_customer_reference: str | None = None
    default_contact_email: EmailStr | None = None
    # Read from UPSTREAM_RETRY_*.
    retry: RetrySettings = Field(default_factory=KyckrRetrySettings)
