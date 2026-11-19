from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic.alias_generators import to_camel

_CAMEL: ConfigDict = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AccessEntry(BaseModel):
    """A single access entry granting a user or group access to a space."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    id: str = Field(description="Access entry ID.")
    entity_id: str = Field(description="ID of the user or group.")
    entity_type: str = Field(description="'USER' or 'GROUP'.")
    type: str = Field(description="Access level: 'USE', 'MANAGE', or 'UPLOAD'.")


class SpaceAccessResponse(BaseModel):
    """Access entries currently granted on a space."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    access: list[AccessEntry] = Field(description="List of access entries.")


class DeleteSpaceAccessResponse(BaseModel):
    """Result of a delete space access operation."""

    success: bool = Field(description="True if the access entries were removed.")


class McpServerToolStatus(BaseModel):
    """An individual tool on an MCP server."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    name: str = Field(description="Tool name as registered on the MCP server.")
    is_enabled: bool = Field(description="Whether this tool is currently enabled on the space.")


class McpServerStatus(BaseModel):
    """Runtime status of an MCP server for a specific space."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    mcp_server_id: str = Field(description="ID of the MCP server.")
    name: str = Field(description="Human-readable name of the MCP server.")
    is_enabled: bool = Field(description="Whether the server is enabled for this space.")
    requires_oauth: bool = Field(
        alias="requiresOAuth",
        description="Whether the server requires an OAuth connection.",
    )
    is_o_auth2_connected: bool = Field(
        description="Whether the user has connected via OAuth2 for this server."
    )
    oauth2_url: str | None = Field(
        default=None,
        description="OAuth2 authorization URL to connect, if requiresOAuth is true.",
    )
    enabled_tool_names: list[str] = Field(
        description="Names of tools currently enabled for this space."
    )


class McpServerStatusResponse(BaseModel):
    """MCP server status for all servers connected to a space."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    space_id: str = Field(description="ID of the space.")
    mcp_servers: list[McpServerStatus] = Field(description="Status of each MCP server.")


class McpServerToolInfo(BaseModel):
    """A tool offered by an MCP server in the catalogue."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    name: str = Field(description="Tool name.")
    description: str | None = Field(default=None, description="Tool description.")


class McpServerInfo(BaseModel):
    """An MCP server available for connection to spaces."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    id: str = Field(description="Server ID.")
    name: str = Field(description="Human-readable server name.")
    description: str | None = Field(default=None, description="Server description.")
    requires_oauth: bool = Field(
        alias="requiresOAuth",
        description="Whether connecting requires an OAuth flow.",
    )
    is_space_restricted: bool = Field(
        description="Whether this server can only be added to specific spaces."
    )
    allowed_space_ids: list[str] = Field(
        description="Space IDs this server may be added to (empty when not space-restricted)."
    )
    tools: list[McpServerToolInfo] = Field(description="Tools offered by this server.")


class McpServersListResponse(BaseModel):
    """Catalogue of available MCP servers."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    mcp_servers: list[McpServerInfo] = Field(description="Available MCP servers.")


class LanguageModelsResponse(BaseModel):
    """Language models available for selection in this environment."""

    models: list[str] = Field(description="Model identifiers available for configuration.")
