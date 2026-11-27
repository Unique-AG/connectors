from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic.alias_generators import to_camel

_CAMEL: ConfigDict = ConfigDict(
    alias_generator=to_camel,
    populate_by_name=True,
)


class SwitchableLanguageModel(BaseModel):
    """A language model available for selection in the space settings."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    display_name: str = Field(description="Human-readable label shown in the UI.")
    language_model: str = Field(description="Model identifier, e.g. 'AZURE_GPT_4o_2024_1120'.")


class AssistantPrompt(BaseModel):
    """A custom prompt shown as a suggestion in the chat UI."""

    title: str = Field(description="Button label displayed in the chat UI.")
    prompt: str = Field(description="Prompt text inserted into the chat input when selected.")
    id: str | None = Field(default=None, description="Prompt ID assigned by the platform.")
    order: int | None = Field(
        default=None, description="Display order among prompts (lower = first)."
    )


class McpServerTool(BaseModel):
    """A single tool within an MCP server configuration."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    name: str = Field(description="Tool name as registered on the MCP server.")
    is_enabled: bool = Field(description="Whether this tool is enabled for the space.")


class McpServerParam(BaseModel):
    """An MCP server attached to the space and its tool selection."""

    model_config: ClassVar[ConfigDict] = _CAMEL

    mcp_server_id: str = Field(description="ID of the MCP server to attach.")
    tools: list[McpServerTool] | None = Field(
        default=None,
        description="Per-tool enable/disable overrides. Omit to keep existing selection.",
    )
