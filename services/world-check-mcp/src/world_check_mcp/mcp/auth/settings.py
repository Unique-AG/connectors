from enum import StrEnum
from typing import ClassVar

from mcp_configs import shared_config
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class AuthMode(StrEnum):
    ZITADEL = "zitadel"
    # Only for a server on loopback, which `run_server` keeps a server without auth to.
    NONE = "none"


class AuthSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config("MCP_AUTH_")

    mode: AuthMode = AuthMode.ZITADEL
