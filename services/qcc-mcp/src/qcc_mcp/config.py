"""Configuration — QCC credentials and gateway settings, from env or `.env`.

Unlike office-365-mcp there is no OAuth: QCC authenticates every call with a
static API key + secret signature, so config is just the credential pair and
the gateway base URL. Use the sandbox (`sbox-…`) key for testing, the prod key
for real data.

Env vars (prefix `QCC_`):  QCC_API_KEY, QCC_SECRET_KEY, QCC_BASE_URL (optional).
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class QccConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QCC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: SecretStr = Field(description="QCC API key, sent in the ApiKey header.")
    secret_key: SecretStr = Field(description="QCC secret key; used to sign, never transmitted.")
    base_url: str = Field(
        default="https://gateway.qcckyc.com/api/external/customer",
        description="Gateway base URL.",
    )
    timeout_s: int = Field(default=30, description="Per-request HTTP timeout in seconds.")
