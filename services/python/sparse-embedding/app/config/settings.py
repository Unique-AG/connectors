"""
Application settings and environment variables.

Environment Loading Priority:
1. System environment variables (highest priority)
2. .env file (fallback if system env not set)
3. Field defaults (used if neither above is set)

Usage:
    # Default: loads from .env if present, otherwise system env vars
    from app.config.settings import settings

    # Override env file for testing:
    ENV_FILE=.env.test python main.py
"""

import os
from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Application environment types."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Logging level options."""

    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(  # pyright: ignore[reportUnannotatedClassAttribute]
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    python_env: Environment = Field(
        default=Environment.DEVELOPMENT, description="The application environment"
    )

    log_level: LogLevel = Field(
        default=LogLevel.INFO, description="The logging level for the application"
    )

    temporal_task_queue: str = Field(
        default="python-queue", description="The temporal task queue to use"
    )

    grpc_port: int = Field(
        default=50051, description="The gRPC server port"
    )


settings: Settings = Settings()
