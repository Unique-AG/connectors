from typing import ClassVar

from mcp_configs import shared_config
from pydantic import Field
from pydantic import HttpUrl
from pydantic import model_validator
from pydantic import PostgresDsn
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config()

    public_base_url: HttpUrl = Field(validation_alias="UNIQUE_MCP_PUBLIC_BASE_URL")
    zitadel_base_url: str = Field(validation_alias="ZITADEL_BASE_URL")
    zitadel_client_id: str = Field(validation_alias="ZITADEL_CLIENT_ID")
    zitadel_jwt_signing_key: SecretStr = Field(validation_alias="ZITADEL_JWT_SIGNING_KEY")
    database_url: PostgresDsn | None = Field(default=None)
    encryption_key: SecretStr | None = Field(default=None, min_length=64, max_length=64)
    allow_ephemeral_oauth_storage: bool = Field(default=False)

    @model_validator(mode="after")
    def _storage_must_be_durable(self) -> AuthSettings:
        durable = bool(self.database_url and self.encryption_key)
        half = bool(self.database_url) ^ bool(self.encryption_key)
        if half:
            raise ValueError(
                "OAuth storage is half-configured: set BOTH DATABASE_URL and "
                "ENCRYPTION_KEY, or neither (with "
                "ALLOW_EPHEMERAL_OAUTH_STORAGE=true for local dev)."
            )
        if durable and self.allow_ephemeral_oauth_storage:
            raise ValueError(
                "Refuse ALLOW_EPHEMERAL_OAUTH_STORAGE when DATABASE_URL and "
                "ENCRYPTION_KEY are set — pick durable or ephemeral, not both."
            )
        if durable:
            assert self.encryption_key is not None
            try:
                bytes.fromhex(self.encryption_key.get_secret_value())
            except ValueError as exc:
                raise ValueError(
                    "ENCRYPTION_KEY is the right length but not valid hex. "
                    "Generate one with: openssl rand -hex 32"
                ) from exc
            return self
        if self.allow_ephemeral_oauth_storage:
            return self
        raise ValueError(
            "OAuth storage is not durable: set DATABASE_URL + ENCRYPTION_KEY, "
            "or set ALLOW_EPHEMERAL_OAUTH_STORAGE=true for local dev. "
            "Ephemeral storage logs out every user on pod restart."
        )
