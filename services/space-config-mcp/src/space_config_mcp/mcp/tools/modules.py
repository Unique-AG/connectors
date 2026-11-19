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
from space_config_mcp.mcp.dependencies import get_persistence
from space_config_mcp.mcp.dependencies import get_space_id
from space_config_mcp.mcp.dependencies import get_upstream
from space_config_mcp.persistence import Persistence
from space_config_mcp.shared import ClaudeEffort
from space_config_mcp.shared import ClaudeSDKConfig
from space_config_mcp.shared import CodexReasoningEffort
from space_config_mcp.shared import CodexSDKConfig
from space_config_mcp.shared import ConductConfig
from space_config_mcp.shared import ConductSetupConfig
from space_config_mcp.shared import ConductStrategy
from space_config_mcp.shared import MagicTableExportAssistant
from space_config_mcp.shared import MagicTableSpaceSettings
from space_config_mcp.shared import McpIntegrationMode
from space_config_mcp.shared import PermissionMode
from space_config_mcp.shared import PiAgentSDKConfig
from space_config_mcp.shared import PiAgentThinkingLevel
from space_config_mcp.shared import ProcessingStep
from space_config_mcp.shared import RfpColumn
from space_config_mcp.shared import RfpModuleConfig
from space_config_mcp.shared import SpaceConfigError
from space_config_mcp.shared import TranslationConfig
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
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Module:
    """Get a single module with its full configuration dict.

    Call list_modules first to find module IDs.
    """
    user_id, company_id = caller
    return await contexts.get_module(
        upstream=upstream,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        module_id=module_id,
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
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Module:
    """Merge config_patch into a module's configuration dict. Existing unpatched keys are kept."""
    user_id, company_id = caller
    return await contexts.update_module_config(
        upstream=upstream,
        persistence=persistence,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
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
    annotations=ToolAnnotations(idempotent_hint=False),
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
    max_history_interactions: Annotated[
        int | None,
        Field(
            description=(
                "Maximum number of past chat messages included as history context "
                "(setup.maxHistoryInteractions). Set to 0 to disable history."
            ),
            ge=0,
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
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Module:
    """Update the current space's SwappableIntelligence harness configuration.

    Each parameter targets a specific key in the stored configuration. Only provided
    (non-None) parameters are written; everything else in the existing config is preserved.
    Use get_conduct_config first to inspect the current state.
    Creates a pre-update snapshot before applying changes.
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
            max_history_interactions,
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
            max_history_interactions=max_history_interactions,
            show_thinking_in_chat=show_thinking_in_chat,
            show_tool_calls_in_chat=show_tool_calls_in_chat,
            progress_update_abort_s=progress_update_abort_s,
        )

    try:
        return await contexts.update_conduct_config(
            upstream=upstream,
            persistence=persistence,
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


@tool(
    title="Get Translator Config",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_translator_config(
    *,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> dict[str, object]:
    """Return the TranslatorV2 module ID and its typed TranslationConfig for the current space.

    The configuration dict uses camelCase keys. Use this before calling
    update_translator_config to inspect the current state.
    """
    user_id, company_id = caller
    try:
        return await contexts.get_translator_config(
            upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
        )
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    title="Update Translator Config",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def update_translator_config(
    *,
    language_model_translation: Annotated[
        str | None,
        Field(description="Model used for the translation step, e.g. 'AZURE_GPT_4o_2024_1120'."),
    ] = None,
    language_model_language_detection: Annotated[
        str | None,
        Field(description="Model used for language detection."),
    ] = None,
    temperature_translation: Annotated[
        float | None,
        Field(
            description="Sampling temperature for translation (0–2). Lower = more deterministic.",
            ge=0,
            le=2,
        ),
    ] = None,
    streaming_activated: Annotated[
        bool | None,
        Field(description="Stream translation tokens to the UI as they arrive."),
    ] = None,
    custom_output_token_limit: Annotated[
        int | None,
        Field(
            description=(
                "Override the model's default output token limit. "
                "Set to null to use the model default."
            )
        ),
    ] = None,
    scope_id_translation_glossary: Annotated[
        str | None,
        Field(description="Scope ID of the KB folder containing the translation glossary."),
    ] = None,
    file_name_translation_glossary: Annotated[
        str | None,
        Field(description="File name of the glossary file within the glossary scope."),
    ] = None,
    pre_processing: Annotated[
        list[ProcessingStep] | None,
        Field(
            description=(
                "Steps applied before translation. Providing this list replaces all existing ones."
            )
        ),
    ] = None,
    post_processing: Annotated[
        list[ProcessingStep] | None,
        Field(
            description=(
                "Steps applied after translation. Providing this list replaces all existing ones."
            )
        ),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Module:
    """Update the current space's TranslatorV2 module configuration.

    Only provided (non-None) parameters are written; everything else in the existing config
    is preserved. Use get_translator_config first to inspect the current state.
    Creates a pre-update snapshot before applying changes.
    """
    user_id, company_id = caller
    patch = TranslationConfig(
        language_model_translation=language_model_translation,
        language_model_language_detection=language_model_language_detection,
        temperature_translation=temperature_translation,
        streaming_activated=streaming_activated,
        custom_output_token_limit=custom_output_token_limit,
        scope_id_translation_glossary=scope_id_translation_glossary,
        file_name_translation_glossary=file_name_translation_glossary,
        pre_processing=pre_processing,
        post_processing=post_processing,
    )
    try:
        return await contexts.update_translator_config(
            upstream=upstream,
            persistence=persistence,
            user_id=user_id,
            company_id=company_id,
            space_id=space_id,
            patch=patch,
        )
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    title="Get Magic Table Config",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_magic_table_config(
    *,
    target_space_id: Annotated[
        str | None,
        Field(
            description=(
                "ID of the Magic Table space to read. Defaults to the current space. "
                "Set this when calling from a Conduct or command space to read a "
                "Magic Table space that has no chat interface of its own."
            )
        ),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> dict[str, object]:
    """Return the RfpAgent (Magic Table) module ID and its raw configuration.

    Reads the current space by default. Pass target_space_id to read a Magic Table
    space from a Conduct or command space that acts as its configuration interface.
    Use this before calling update_magic_table_config to inspect the current state,
    including the full column list.
    """
    user_id, company_id = caller
    effective_space_id = target_space_id or space_id
    try:
        return await contexts.get_magic_table_config(
            upstream=upstream,
            user_id=user_id,
            company_id=company_id,
            space_id=effective_space_id,
        )
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    title="Update Magic Table Config",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def update_magic_table_config(  # noqa: PLR0913
    *,
    target_space_id: Annotated[
        str | None,
        Field(
            description=(
                "ID of the Magic Table space to update. Defaults to the current space. "
                "Set this when calling from a Conduct or command space to configure a "
                "Magic Table space that has no chat interface of its own."
            )
        ),
    ] = None,
    language_model: Annotated[
        str | None,
        Field(description="Default language model for all columns that don't override it."),
    ] = None,
    columns: Annotated[
        list[RfpColumn] | None,
        Field(
            description=(
                "Full column list. Providing this replaces all existing columns. "
                "Use get_magic_table_config to fetch columns you don't want to change."
            )
        ),
    ] = None,
    auto_reprocess_on_source_add: Annotated[
        bool | None,
        Field(
            description=("If True, automatically reprocess all rows when new sources are added.")
        ),
    ] = None,
    hallucination_enabled: Annotated[
        bool | None,
        Field(description="Enable the hallucination check column."),
    ] = None,
    question_extraction_language_model: Annotated[
        str | None,
        Field(description="Model used to extract questions from uploaded documents."),
    ] = None,
    question_extraction_use_full_document: Annotated[
        bool | None,
        Field(
            description=(
                "Extract questions from the full document in one call rather than chunk-by-chunk."
            )
        ),
    ] = None,
    question_extraction_max_rows: Annotated[
        int | None,
        Field(
            description="Maximum number of questions to extract per document.",
            ge=1,
        ),
    ] = None,
    answer_library: Annotated[
        bool | None,
        Field(description="Show the Answer Library section to space members."),
    ] = None,
    hide_sheet_status: Annotated[
        bool | None,
        Field(description="Hide the sheet status indicator from users."),
    ] = None,
    export_assistants: Annotated[
        list[MagicTableExportAssistant] | None,
        Field(
            description=(
                "Assistants available in the export menu. "
                "Providing this list replaces all existing export assistants."
            )
        ),
    ] = None,
    answer_library_access_entity_ids: Annotated[
        list[str] | None,
        Field(
            description=(
                "Restrict Answer Library access to these entity IDs. "
                "Omit to show it to every space member."
            )
        ),
    ] = None,
    disable_notifications_by_default: Annotated[
        bool | None,
        Field(description="Hide the sheet notification toggle and keep default assignee emails."),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Module:
    """Update a Magic Table space's RfpAgent module and/or space-level settings.

    Updates the current space by default. Pass target_space_id to configure a Magic Table
    space from a Conduct or command space that acts as its configuration interface.
    Module-level parameters (language_model, columns, etc.) patch the RfpAgent module config.
    Space-level parameters (answer_library, hide_sheet_status, etc.) patch
    space.settings.magicTableConfig. Only provided (non-None) parameters are written.
    Use get_magic_table_config first to inspect the current state.
    Creates a pre-update snapshot before applying changes.
    """
    user_id, company_id = caller
    effective_space_id = target_space_id or space_id

    module_patch: RfpModuleConfig | None = None
    if any(
        v is not None
        for v in (
            language_model,
            columns,
            auto_reprocess_on_source_add,
            hallucination_enabled,
            question_extraction_language_model,
            question_extraction_use_full_document,
            question_extraction_max_rows,
        )
    ):
        module_patch = RfpModuleConfig(
            language_model=language_model,
            columns=columns,
            auto_reprocess_on_source_add=auto_reprocess_on_source_add,
            hallucination_enabled=hallucination_enabled,
            question_extraction_language_model=question_extraction_language_model,
            question_extraction_use_full_document=question_extraction_use_full_document,
            question_extraction_max_rows=question_extraction_max_rows,
        )

    space_settings_patch: MagicTableSpaceSettings | None = None
    if any(
        v is not None
        for v in (
            answer_library,
            hide_sheet_status,
            export_assistants,
            answer_library_access_entity_ids,
            disable_notifications_by_default,
        )
    ):
        space_settings_patch = MagicTableSpaceSettings(
            answer_library=answer_library,
            hide_sheet_status=hide_sheet_status,
            export_assistants=export_assistants,
            answer_library_access_entity_ids=answer_library_access_entity_ids,
            disable_notifications_by_default=disable_notifications_by_default,
        )

    try:
        return await contexts.update_magic_table_config(
            upstream=upstream,
            persistence=persistence,
            user_id=user_id,
            company_id=company_id,
            space_id=effective_space_id,
            module_patch=module_patch,
            space_settings_patch=space_settings_patch,
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
    "MagicTableExportAssistant",
    "MagicTableSpaceSettings",
    "McpIntegrationMode",
    "PermissionMode",
    "PiAgentSDKConfig",
    "PiAgentThinkingLevel",
    "ProcessingStep",
    "RfpColumn",
    "RfpModuleConfig",
    "TranslationConfig",
    "get_conduct_config",
    "get_magic_table_config",
    "get_module",
    "get_translator_config",
    "list_modules",
    "update_conduct_config",
    "update_magic_table_config",
    "update_module_config",
    "update_translator_config",
]
