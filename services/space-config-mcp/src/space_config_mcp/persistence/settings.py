from typing import ClassVar

from mcp_configs import shared_config
from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class PersistenceSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = shared_config("SPACE_CONFIG_MCP_")

    kb_scope_id: str | None = Field(
        default=None,
        description=(
            "Scope ID of the parent KB folder (e.g. your skills-conduct folder). "
            "The MCP creates a 'space-config-history' sub-folder inside it on first use. "
            "Find the ID via the Unique admin portal or: unique-cli kb ls --show-ids"
        ),
    )
