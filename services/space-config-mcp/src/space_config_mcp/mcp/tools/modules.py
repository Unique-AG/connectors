from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field
from unique_mcp.meta.context_requirements import ContextRequirements
from unique_mcp.meta.keys import MetaKeys
from unique_mcp.meta.part import merge_tool_meta
import unique_sdk

from space_config_mcp import contexts
from space_config_mcp.mcp.dependencies import get_caller
from space_config_mcp.mcp.dependencies import get_space_id
from space_config_mcp.mcp.dependencies import get_upstream
from space_config_mcp.shared import ClaudeEffort
from space_config_mcp.shared import ClaudeSDKConfig
from space_config_mcp.shared import CodexReasoningEffort
from space_config_mcp.shared import CodexSDKConfig
from space_config_mcp.shared import ConductConfig
from space_config_mcp.shared import ConductSetupConfig
from space_config_mcp.shared import ConductStrategy
from space_config_mcp.shared import McpIntegrationMode
from space_config_mcp.shared import PermissionMode
from space_config_mcp.shared import PiAgentSDKConfig
from space_config_mcp.shared import PiAgentThinkingLevel
from space_config_mcp.shared import SpaceConfigError
from space_config_mcp.upstream import Upstream

_META = merge_tool_meta(
    {},
    ContextRequirements(required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID, MetaKeys.ASSISTANT_ID]),
)


@tool(
    title="List Modules",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def list_modules(
    *,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> list[unique_sdk.Module]:
    """List all modules belonging to the current space."""
    user_id, company_id = caller
    return await contexts.list_modules(
        upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
    )


@tool(
    title="Get Module",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_module(
    *,
    module_id: Annotated[str, Field(description="ID of the module to retrieve.")],
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
) -> unique_sdk.Module:
    """Get a single module with its full configuration dict."""
    user_id, company_id = caller
    return await contexts.get_module(
        upstream=upstream, user_id=user_id, company_id=company_id, module_id=module_id
    )


@tool(
    title="Update Module Config",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def update_module_config(
    *,
    module_id: Annotated[str, Field(description="ID of the module to update.")],
    config_patch: Annotated[
        dict[str, object],
        Field(
            description=(
                "Keys to merge into the module's configuration dict. "
                "Existing keys not in the patch are preserved. "
                "For Conduct spaces, prefer update_conduct_config instead."
            )
        ),
    ],
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
) -> unique_sdk.Module:
    """Merge config_patch into a module's configuration dict. Existing unpatched keys are kept."""
    user_id, company_id = caller
    return await contexts.update_module_config(
        upstream=upstream,
        user_id=user_id,
        company_id=company_id,
        module_id=module_id,
        config_patch=config_patch,
    )


@tool(
    title="Get Conduct Config",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_conduct_config(
    *,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> dict[str, object]:
    """Return the SwappableIntelligence module ID and its typed ConductConfig for the current space.

    The configuration dict uses camelCase keys matching the stored format. Use this before
    calling update_conduct_config to inspect the current state.
    """
    user_id, company_id = caller
    try:
        return await contexts.get_conduct_config(
            upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
        )
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    title="Update Conduct Config",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=True),
)
async def update_conduct_config(  # noqa: PLR0913
    *,
    strategy: Annotated[
        ConductStrategy | None,
        Field(
            description=(
                "Agent execution strategy. 'claude_code' is the standard Claude Code runner. "
                "'pi_agent' uses a Pi-model runner. 'codex' uses an OpenAI Codex runner."
            )
        ),
    ] = None,
    max_turns: Annotated[
        int | None,
        Field(
            description=(
                "Maximum agent turns (1–1000). Applied to the active strategy block "
                "(claude.maxTurns, piAgent.maxTurns, or codex.maxTurns)."
            ),
            ge=1,
            le=1000,
        ),
    ] = None,
    claude_model: Annotated[
        str | None,
        Field(description="Claude model ID for the claude_code/claude_sandbox strategy."),
    ] = None,
    claude_effort: Annotated[
        ClaudeEffort | None,
        Field(description="Reasoning effort level for the claude_code strategy."),
    ] = None,
    claude_permission_mode: Annotated[
        PermissionMode | None,
        Field(
            description=(
                "Tool permission mode for the claude_code strategy. "
                "'bypassPermissions' skips all confirmation prompts."
            )
        ),
    ] = None,
    claude_max_context_tokens: Annotated[
        int | None,
        Field(
            description="Maximum context window tokens for claude_code (50 000–500 000).",
            ge=50000,
            le=500000,
        ),
    ] = None,
    claude_autocompact_pct: Annotated[
        int | None,
        Field(
            description="Context autocompact threshold percentage for claude_code (10–95).",
            ge=10,
            le=95,
        ),
    ] = None,
    pi_agent_model_name: Annotated[
        str | None,
        Field(description="Model ID for the pi_agent strategy."),
    ] = None,
    pi_agent_thinking_level: Annotated[
        PiAgentThinkingLevel | None,
        Field(description="Thinking depth for the pi_agent strategy."),
    ] = None,
    codex_model: Annotated[
        str | None,
        Field(description="Model ID for the codex strategy."),
    ] = None,
    codex_reasoning_effort: Annotated[
        CodexReasoningEffort | None,
        Field(description="Reasoning effort level for the codex strategy."),
    ] = None,
    custom_instructions: Annotated[
        str | None,
        Field(
            description=(
                "Instructions appended to the agent system prompt (setup.customInstructions)."
            )
        ),
    ] = None,
    system_prompt_override: Annotated[
        str | None,
        Field(
            description=(
                "When non-empty, fully replaces the agent system prompt "
                "(setup.systemPromptOverride)."
            )
        ),
    ] = None,
    agent_md_instructions: Annotated[
        str | None,
        Field(
            description=(
                "Admin AGENT.md content injected into the workspace (setup.agentMdInstructions)."
            )
        ),
    ] = None,
    enable_code_execution: Annotated[
        bool | None,
        Field(
            description=("Enable bash/write/read tools in the agent (setup.enableCodeExecution).")
        ),
    ] = None,
    enable_browser_control: Annotated[
        bool | None,
        Field(description="Enable browser automation tools (setup.enableBrowserControl)."),
    ] = None,
    mcp_integration_mode: Annotated[
        McpIntegrationMode | None,
        Field(
            description=(
                "How MCP servers are exposed to the agent: as 'tools' or 'skills' "
                "(setup.mcpIntegrationMode)."
            )
        ),
    ] = None,
    show_thinking_in_chat: Annotated[
        bool | None,
        Field(description="Show agent thinking steps in the chat UI (setup.showThinkingInChat)."),
    ] = None,
    show_tool_calls_in_chat: Annotated[
        bool | None,
        Field(description="Show tool calls in the chat UI (setup.showToolCallsInChat)."),
    ] = None,
    progress_update_abort_s: Annotated[
        float | None,
        Field(
            description=(
                "Abort the agent after this many seconds without a progress update. "
                "Set to null/None to disable (setup.progressUpdateAbortS)."
            ),
            ge=0,
        ),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Module:
    """Update the current space's SwappableIntelligence harness configuration.

    Each parameter targets a specific key in the stored configuration. Only provided
    (non-None) parameters are written; everything else in the existing config is preserved.
    Use get_conduct_config first to inspect the current state.
    """
    user_id, company_id = caller
    claude_patch: ClaudeSDKConfig | None = None
    if any(
        v is not None
        for v in (
            claude_model,
            claude_effort,
            claude_permission_mode,
            claude_max_context_tokens,
            claude_autocompact_pct,
        )
    ):
        claude_patch = ClaudeSDKConfig(
            model=claude_model,
            effort=claude_effort,
            permission_mode=claude_permission_mode,
            max_context_tokens=claude_max_context_tokens,
            autocompact_pct=claude_autocompact_pct,
        )

    pi_agent_patch: PiAgentSDKConfig | None = None
    if any(v is not None for v in (pi_agent_model_name, pi_agent_thinking_level)):
        pi_agent_patch = PiAgentSDKConfig(
            model_name=pi_agent_model_name,
            thinking_level=pi_agent_thinking_level,
        )

    codex_patch: CodexSDKConfig | None = None
    if any(v is not None for v in (codex_model, codex_reasoning_effort)):
        codex_patch = CodexSDKConfig(
            model=codex_model,
            model_reasoning_effort=codex_reasoning_effort,
        )

    setup_patch: ConductSetupConfig | None = None
    if any(
        v is not None
        for v in (
            custom_instructions,
            system_prompt_override,
            agent_md_instructions,
            enable_code_execution,
            enable_browser_control,
            mcp_integration_mode,
            show_thinking_in_chat,
            show_tool_calls_in_chat,
            progress_update_abort_s,
        )
    ):
        setup_patch = ConductSetupConfig(
            custom_instructions=custom_instructions,
            system_prompt_override=system_prompt_override,
            agent_md_instructions=agent_md_instructions,
            enable_code_execution=enable_code_execution,
            enable_browser_control=enable_browser_control,
            mcp_integration_mode=mcp_integration_mode,
            show_thinking_in_chat=show_thinking_in_chat,
            show_tool_calls_in_chat=show_tool_calls_in_chat,
            progress_update_abort_s=progress_update_abort_s,
        )

    try:
        return await contexts.update_conduct_config(
            upstream=upstream,
            user_id=user_id,
            company_id=company_id,
            space_id=space_id,
            strategy=strategy,
            max_turns=max_turns,
            claude_patch=claude_patch,
            pi_agent_patch=pi_agent_patch,
            codex_patch=codex_patch,
            setup_patch=setup_patch,
        )
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc


# Re-export enums so they are importable from this module by the architecture check.
__all__ = [
    "ClaudeEffort",
    "ClaudeSDKConfig",
    "CodexReasoningEffort",
    "CodexSDKConfig",
    "ConductConfig",
    "ConductSetupConfig",
    "ConductStrategy",
    "McpIntegrationMode",
    "PermissionMode",
    "PiAgentSDKConfig",
    "PiAgentThinkingLevel",
    "get_conduct_config",
    "get_module",
    "list_modules",
    "update_conduct_config",
    "update_module_config",
]
