from typing import ClassVar, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

_CAMEL: ConfigDict = ConfigDict(
    alias_generator=to_camel,
    populate_by_name=True,
)

ConductStrategy = Literal["claude_code", "pi_agent", "codex", "cursor_sdk", "claude_sandbox"]
ClaudeEffort = Literal["auto", "low", "medium", "high", "xhigh", "max"]
PermissionMode = Literal["default", "acceptEdits", "bypassPermissions"]
PiAgentThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
CodexReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
McpIntegrationMode = Literal["tools", "skills"]


class ConductSetupConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = _CAMEL

    enable_workspace_persistence: bool | None = None
    enable_code_execution: bool | None = None
    enable_browser_control: bool | None = None
    mcp_integration_mode: McpIntegrationMode | None = None
    subagent_integration_mode: Literal["skills", "tools"] | None = None
    add_dirs: list[str] | None = None
    history_included: bool | None = None
    max_history_interactions: int | None = None
    custom_instructions: str | None = None
    system_prompt_override: str | None = None
    user_instructions: str | None = None
    agent_md_instructions: str | None = None
    show_thinking_in_chat: bool | None = None
    show_tool_calls_in_chat: bool | None = None
    show_run_stats_in_chat: bool | None = None
    enable_user_memory: bool | None = None
    show_memory_in_chat: bool | None = None
    progress_update_abort_s: float | None = None
    checkpoint_interval_turns: int | None = None
    enable_hallucination_check: bool | None = None
    enable_skill_creation: bool | None = None


class ClaudeSDKConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = _CAMEL

    model: str | None = None
    effort: ClaudeEffort | None = None
    fallback_model: str | None = None
    max_thinking_tokens: int | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    permission_mode: PermissionMode | None = None
    verbose_logging: bool | None = None
    enable_context_guard: bool | None = None
    max_context_tokens: int | None = None
    max_session_tokens: int | None = None
    persistent_client: bool | None = None
    autocompact_pct: int | None = None
    block_unfinished_plan_stop: bool | None = None
    plan_stop_block_cap: int | None = None


class PiAgentSDKConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = _CAMEL

    model_name: str | None = None
    thinking_level: PiAgentThinkingLevel | None = None
    max_turns: int | None = None
    auto_compact_pct: int | None = None
    enabled_extensions: list[str] | None = None
    verbose_logging: bool | None = None
    enable_context_guard: bool | None = None


class CodexSDKConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = _CAMEL

    model: str | None = None
    model_reasoning_effort: CodexReasoningEffort | None = None
    max_turns: int | None = None


class ConductSpaceConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = _CAMEL

    project_name: str | None = None


class ConductToolConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = _CAMEL

    name: str
    is_enabled: bool = True
    configuration: dict[str, object] = {}


class ConductConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = _CAMEL

    strategy: ConductStrategy | None = None
    space: ConductSpaceConfig | None = None
    setup: ConductSetupConfig | None = None
    tools: list[ConductToolConfig] | None = None
    claude: ClaudeSDKConfig | None = None
    pi_agent: PiAgentSDKConfig | None = None
    codex: CodexSDKConfig | None = None
    added_models: list[object] | None = None


__all__ = [
    "ClaudeEffort",
    "ClaudeSDKConfig",
    "CodexReasoningEffort",
    "CodexSDKConfig",
    "ConductConfig",
    "ConductSetupConfig",
    "ConductSpaceConfig",
    "ConductStrategy",
    "ConductToolConfig",
    "McpIntegrationMode",
    "PermissionMode",
    "PiAgentSDKConfig",
    "PiAgentThinkingLevel",
]
