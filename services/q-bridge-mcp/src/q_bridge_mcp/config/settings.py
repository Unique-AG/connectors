from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import ClassVar

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = Field(
        default="0.0.0.0",
        description="The host that the MCP server binds to",
    )
    port: int = Field(
        default=8000,
        ge=0,
        le=65535,
        description="The port that the MCP server listens on",
    )
    python_env: Environment = Field(
        default=Environment.DEVELOPMENT,
        description="The runtime environment",
    )

    mcp_base_url: AnyHttpUrl = Field(
        description="The public base URL of the MCP server",
    )
    mcp_jwt_signing_key: SecretStr = Field(
        min_length=32,
        description="Secret used to sign FastMCP access tokens",
    )
    storage_path: Path = Field(
        default=Path(".fastmcp"),
        description="Directory for development OAuth storage",
    )
    storage_encryption_key: SecretStr = Field(
        min_length=44,
        description="Fernet key used to encrypt OAuth storage",
    )

    redis_host: str | None = Field(
        default=None,
        description="Redis hostname for production OAuth storage",
    )
    redis_port: int = Field(
        default=6379,
        ge=1,
        le=65535,
        description="Redis port for production OAuth storage",
    )
    redis_database: int = Field(
        default=0,
        ge=0,
        description="Redis database for production OAuth storage",
    )
    redis_password: SecretStr | None = Field(
        default=None,
        description="Optional Redis password for production OAuth storage",
    )
    redis_ssl: bool = Field(
        default=False,
        description="Use TLS for the production Redis connection",
    )

    zitadel_issuer_url: AnyHttpUrl = Field(
        description="The base URL of the Zitadel OIDC issuer",
    )
    zitadel_client_id: str = Field(
        min_length=1,
        description="The Zitadel OAuth application client ID",
    )
    zitadel_client_secret: SecretStr = Field(
        min_length=1,
        description="The Zitadel OAuth application client secret",
    )

    @property
    def zitadel_openid_configuration(self) -> str:
        return (
            f"{str(self.zitadel_issuer_url).rstrip('/')}"
            "/.well-known/openid-configuration"
        )


settings: Settings = Settings()  # pyright: ignore[reportCallIssue]
