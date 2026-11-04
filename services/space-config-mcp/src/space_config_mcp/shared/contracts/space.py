from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

_CAMEL: ConfigDict = ConfigDict(
    alias_generator=to_camel,
    populate_by_name=True,
)


class SwitchableLanguageModel(BaseModel):
    model_config: ClassVar[ConfigDict] = _CAMEL

    display_name: str
    language_model: str


class AssistantPrompt(BaseModel):
    title: str
    prompt: str
    id: str | None = None
    order: int | None = None


class McpServerTool(BaseModel):
    model_config: ClassVar[ConfigDict] = _CAMEL

    name: str
    is_enabled: bool


class McpServerParam(BaseModel):
    model_config: ClassVar[ConfigDict] = _CAMEL

    mcp_server_id: str
    tools: list[McpServerTool] | None = None
