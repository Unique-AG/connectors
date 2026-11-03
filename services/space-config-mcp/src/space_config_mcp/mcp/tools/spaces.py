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
from space_config_mcp.upstream import Upstream

_META = merge_tool_meta(
    {},
    ContextRequirements(required=[MetaKeys.USER_ID, MetaKeys.COMPANY_ID, MetaKeys.ASSISTANT_ID]),
)


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
    """Get the full configuration of the current space: metadata, modules, scope rules, and access."""
    user_id, company_id = caller
    return await contexts.get_space(
        upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
    )


@tool(
    title="Update Space",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=True),
)
async def update_space(
    *,
    name: Annotated[str | None, Field(description="New display name for the space.")] = None,
    explanation: Annotated[
        str | None, Field(description="Description / system-prompt text for the space.")
    ] = None,
    alert: Annotated[
        str | None, Field(description="Alert text shown to users of the space.")
    ] = None,
    language_model: Annotated[
        str | None, Field(description="Language model identifier, e.g. 'gpt-4o'.")
    ] = None,
    allow_model_switching: Annotated[
        bool | None, Field(description="Whether users may switch models.")
    ] = None,
    is_pinned: Annotated[
        bool | None, Field(description="Pin the space to the top of listings.")
    ] = None,
    settings: Annotated[
        dict[str, object] | None,
        Field(description="Arbitrary settings dict merged at space level."),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Space:
    """Update metadata of the current space. Only the fields you provide are changed."""
    user_id, company_id = caller
    try:
        return await contexts.update_space(
            upstream=upstream,
            user_id=user_id,
            company_id=company_id,
            space_id=space_id,
            name=name,
            explanation=explanation,
            alert=alert,
            language_model=language_model,
            allow_model_switching=allow_model_switching,
            is_pinned=is_pinned,
            settings=settings,
        )
    except Exception as exc:
        raise ToolError(str(exc)) from exc
