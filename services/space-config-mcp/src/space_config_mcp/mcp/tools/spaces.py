from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field
import unique_sdk

from space_config_mcp import contexts
from space_config_mcp.mcp.dependencies import get_caller
from space_config_mcp.mcp.dependencies import get_upstream
from space_config_mcp.upstream import Upstream


@tool(
    title="List Spaces",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def list_spaces(
    *,
    name: Annotated[
        str | None, Field(description="Optional case-insensitive partial name filter.")
    ] = None,
    skip: Annotated[int, Field(description="Number of records to skip for pagination.", ge=0)] = 0,
    take: Annotated[
        int, Field(description="Maximum number of records to return.", ge=1, le=1000)
    ] = 20,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
) -> unique_sdk.Space.Spaces:
    """List Unique AI spaces. Optionally filter by name substring."""
    user_id, company_id = caller
    return await contexts.list_spaces(
        upstream=upstream, user_id=user_id, company_id=company_id, name=name, skip=skip, take=take
    )


@tool(
    title="Get Space",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_space(
    *,
    space_id: Annotated[str, Field(description="ID of the space to retrieve.")],
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
) -> unique_sdk.Space:
    """Get full space configuration: metadata, modules, scope rules, MCP servers, and access."""
    user_id, company_id = caller
    return await contexts.get_space(
        upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
    )


@tool(
    title="Update Space",
    annotations=ToolAnnotations(idempotent_hint=True),
)
async def update_space(
    *,
    space_id: Annotated[str, Field(description="ID of the space to update.")],
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
) -> unique_sdk.Space:
    """Update space metadata. Only the fields you provide are changed."""
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
