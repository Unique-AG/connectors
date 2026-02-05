from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_")

    url: str | None = None
    host: str | None = None
    port: int = 5432
    name: str | None = None
    user: str | None = None
    password: str | None = None

    @model_validator(mode="after")
    def build_url(self) -> "DatabaseConfig":
        if self.url is not None:
            if not self.url.startswith(("postgresql://", "postgresql+")):
                raise ValueError(
                    f"DB_URL must be a PostgreSQL connection string (postgresql://...)"
                )
            if self.url.startswith("postgresql://"):
                self.url = self.url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return self

        missing = [
            name
            for name, val in [
                ("DB_HOST", self.host),
                ("DB_NAME", self.name),
                ("DB_USER", self.user),
                ("DB_PASSWORD", self.password),
            ]
            if val is None
        ]
        if missing:
            raise ValueError(
                f"DB_URL not set; missing required fields: {', '.join(missing)}"
            )
        self.url = (
            f"postgresql+asyncpg://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.name}"
        )
        return self

    @property
    def connection_url(self) -> str:
        """Get the connection URL (guaranteed non-None after validation)."""
        if self.url is None:
            raise RuntimeError("URL should be set after validation")
        return self.url


class RabbitConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RABBITMQ_")

    url: str | None = None
    host: str | None = None
    port: int = 5672
    user: str | None = None
    password: str | None = None
    vhost: str = "/"

    @model_validator(mode="after")
    def build_url(self) -> "RabbitConfig":
        if self.url is not None:
            if not self.url.startswith(("amqp://", "amqps://")):
                raise ValueError(
                    f"RABBITMQ_URL must be an AMQP connection string (amqp://... or amqps://...)"
                )
            return self

        missing = [
            name
            for name, val in [
                ("RABBITMQ_HOST", self.host),
                ("RABBITMQ_USER", self.user),
                ("RABBITMQ_PASSWORD", self.password),
            ]
            if val is None
        ]
        if missing:
            raise ValueError(
                f"RABBITMQ_URL not set; missing required fields: {', '.join(missing)}"
            )
        self.url = (
            f"amqp://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.vhost.lstrip('/')}"
        )
        return self

    @property
    def connection_url(self) -> str:
        """Get the connection URL (guaranteed non-None after validation)."""
        if self.url is None:
            raise RuntimeError("URL should be set after validation")
        return self.url
