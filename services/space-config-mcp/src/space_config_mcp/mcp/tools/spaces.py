from typing import Annotated, Literal

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
from space_config_mcp.shared import AssistantPrompt
from space_config_mcp.shared import LanguageModelsResponse
from space_config_mcp.shared import McpServerParam
from space_config_mcp.shared import McpServersListResponse
from space_config_mcp.shared import McpServerStatusResponse
from space_config_mcp.shared import SwitchableLanguageModel
from space_config_mcp.upstream import Upstream

_META = merge_tool_meta(
    {},
    ContextRequirements(required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID, MetaKeys.ASSISTANT_ID]),
)
_META_COMPANY = merge_tool_meta(
    {},
    ContextRequirements(required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID]),
)
_NEW_CHAT_NOTE = (
    "Language model changes take effect in new chat sessions — "
    "existing chats keep the previous model."
)


@tool(
    title="List Language Models",
    meta=_META_COMPANY,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def list_language_models(
    *,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
) -> LanguageModelsResponse:
    """List all language model IDs available to the company.

    Use this before calling update_space or update_conduct_config to get the exact
    model identifier strings accepted by language_model and switchable_language_models.
    """
    user_id, company_id = caller
    raw = await contexts.list_language_models(
        upstream=upstream, user_id=user_id, company_id=company_id
    )
    return LanguageModelsResponse.model_validate(raw)


@tool(
    title="List MCP Servers",
    meta=_META_COMPANY,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def list_mcp_servers(
    *,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
) -> McpServersListResponse:
    """List all MCP servers (connectors) available to the company.

    Returns each server's id, name, description, requiresOAuth flag, and the full
    list of tool names and descriptions. Use this to find server IDs and tool names
    before calling update_space with mcp_servers.
    """
    user_id, company_id = caller
    raw = await contexts.list_mcp_servers(upstream=upstream, user_id=user_id, company_id=company_id)
    return McpServersListResponse.model_validate(raw)


@tool(
    title="Get Space",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_space(
    *,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Space:
    """Get the current space's full configuration: metadata, modules, scope rules, and access."""
    user_id, company_id = caller
    return await contexts.get_space(
        upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
    )


@tool(
    title="Get MCP Server Status",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_mcp_server_status(
    *,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> McpServerStatusResponse:
    """List MCP servers enabled on the current space with their tool selection and OAuth state."""
    user_id, company_id = caller
    raw = await contexts.get_mcp_server_status(
        upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
    )
    return McpServerStatusResponse.model_validate(raw)


@tool(
    title="Update Space",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def update_space(  # noqa: PLR0913
    *,
    name: Annotated[str | None, Field(description="New display name for the space.")] = None,
    explanation: Annotated[
        str | None, Field(description="Description / system-prompt text for the space.")
    ] = None,
    alert: Annotated[
        str | None, Field(description="Alert text shown to users of the space.")
    ] = None,
    language_model: Annotated[
        str | None, Field(description="Default language model identifier, e.g. 'gpt-4o'.")
    ] = None,
    allow_model_switching: Annotated[
        bool | None, Field(description="Whether users may switch between models.")
    ] = None,
    switchable_language_models: Annotated[
        list[SwitchableLanguageModel] | None,
        Field(
            description=(
                "List of models users can pick from when allow_model_switching is true. "
                "Each entry needs a displayName (shown in the UI) and a languageModel (model ID)."
            )
        ),
    ] = None,
    is_pinned: Annotated[
        bool | None, Field(description="Pin the space to the top of listings.")
    ] = None,
    chat_upload: Annotated[
        Literal["ENABLED", "DISABLED"] | None,
        Field(description="Whether users can upload files in the chat input."),
    ] = None,
    settings: Annotated[
        dict[str, object] | None,
        Field(
            description=(
                "Settings keys to merge at space level. "
                "Platform-managed keys (magicTableConfig) are rejected — "
                "use update_magic_table_config for those."
            )
        ),
    ] = None,
    assistant_prompts: Annotated[
        list[AssistantPrompt] | None,
        Field(
            description=(
                "Preset prompt suggestions shown to users. "
                "Each entry needs a title and a prompt. "
                "Providing this list replaces all existing prompts."
            )
        ),
    ] = None,
    mcp_servers: Annotated[
        list[McpServerParam] | None,
        Field(
            description=(
                "MCP servers (connectors) to configure on the space. "
                "Each entry needs an mcpServerId. "
                "Optionally supply a tools list — each tool entry needs a name and isEnabled. "
                "An empty tools list disables the server. "
                "Omitting tools keeps the existing tool selection for that server. "
                "Use get_mcp_server_status to find server IDs and current tool names."
            )
        ),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> dict[str, object]:
    """Update metadata and configuration of the current space. Only provided fields are changed.

    Creates a pre-update snapshot before applying changes.
    """
    user_id, company_id = caller
    model_changed = language_model is not None or switchable_language_models is not None
    try:
        space = await contexts.update_space(
            upstream=upstream,
            persistence=persistence,
            user_id=user_id,
            company_id=company_id,
            space_id=space_id,
            name=name,
            explanation=explanation,
            alert=alert,
            language_model=language_model,
            allow_model_switching=allow_model_switching,
            switchable_language_models=switchable_language_models,
            is_pinned=is_pinned,
            chat_upload=chat_upload,
            settings=settings,
            assistant_prompts=assistant_prompts,
            mcp_servers=mcp_servers,
        )
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    result: dict[str, object] = dict(space)
    if model_changed:
        result["note"] = _NEW_CHAT_NOTE
    return result
