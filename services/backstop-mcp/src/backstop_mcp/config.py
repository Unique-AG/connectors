from enum import StrEnum
from importlib.metadata import version as pkg_version
from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PKG_VERSION = pkg_version("backstop-mcp")


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


class LogLevel(StrEnum):
    FATAL = "fatal"
    ERROR = "error"
    WARN = "warn"
    INFO = "info"
    DEBUG = "debug"


class AppConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict()

    app_env: AppEnv = AppEnv.PRODUCTION
    version: str = PKG_VERSION
    port: int = Field(default=8000, ge=0, le=65535)
    log_level: LogLevel = LogLevel.INFO


class BackstopConfig(BaseSettings):
    """Where to reach the Backstop REST API.

    Credentials are NOT configured here: each connecting MCP client authenticates as
    themselves by sending their own Backstop `Authorization: Basic ...` (and, for SSO
    users, `token: true`) header, which is forwarded to Backstop unchanged. See
    `backstop_client.py`, and https://backstopsolutions.elevio.help/en/articles/1018 /
    .../236.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(env_prefix="BACKSTOP_")

    base_url: str = "https://api.backstopsolutions.com"
