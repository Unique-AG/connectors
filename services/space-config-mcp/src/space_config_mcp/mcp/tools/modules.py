from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field
import unique_sdk

from space_config_mcp import contexts
from space_config_mcp.mcp.dependencies import get_upstream
from space_config_mcp.shared import SpaceConfigError
from space_config_mcp.upstream import Upstream


@tool(
    title="List Modules",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def list_modules(
    *,
    user_id: Annotated[str, Field(description="Unique platform user ID of the caller.")],
    company_id: Annotated[str, Field(description="Unique platform company ID of the caller.")],
    space_id: Annotated[str, Field(description="ID of the space whose modules to list.")],
    upstream: Upstream = Depends(get_upstream),
) -> list[unique_sdk.Module]:
    """List all modules belonging to a space."""
    return await contexts.list_modules(
        upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
    )


@tool(
    title="Get Module",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_module(
    *,
    user_id: Annotated[str, Field(description="Unique platform user ID of the caller.")],
    company_id: Annotated[str, Field(description="Unique platform company ID of the caller.")],
    module_id: Annotated[str, Field(description="ID of the module to retrieve.")],
    upstream: Upstream = Depends(get_upstream),
) -> unique_sdk.Module:
    """Get a single module with its full configuration dict."""
    return await contexts.get_module(
        upstream=upstream, user_id=user_id, company_id=company_id, module_id=module_id
    )


@tool(
    title="Update Module Config",
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def update_module_config(
    *,
    user_id: Annotated[str, Field(description="Unique platform user ID of the caller.")],
    company_id: Annotated[str, Field(description="Unique platform company ID of the caller.")],
    module_id: Annotated[str, Field(description="ID of the module to update.")],
    config_patch: Annotated[
        dict[str, object],
        Field(
            description=(
                "Keys to merge into the module's configuration dict. "
                "Existing keys not in the patch are preserved."
            )
        ),
    ],
    upstream: Upstream = Depends(get_upstream),
) -> unique_sdk.Module:
    """Merge config_patch into a module's configuration dict. Existing unpatched keys are kept."""
    return await contexts.update_module_config(
        upstream=upstream,
        user_id=user_id,
        company_id=company_id,
        module_id=module_id,
        config_patch=config_patch,
    )


@tool(
    title="Get Conduct Config",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_conduct_config(
    *,
    user_id: Annotated[str, Field(description="Unique platform user ID of the caller.")],
    company_id: Annotated[str, Field(description="Unique platform company ID of the caller.")],
    space_id: Annotated[str, Field(description="ID of the Conduct space.")],
    upstream: Upstream = Depends(get_upstream),
) -> dict[str, object]:
    """Return the SwappableIntelligence module configuration for a Conduct space."""
    try:
        return await contexts.get_conduct_config(
            upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
        )
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    title="Update Conduct Config",
    annotations=ToolAnnotations(idempotent_hint=True),
)
async def update_conduct_config(
    *,
    user_id: Annotated[str, Field(description="Unique platform user ID of the caller.")],
    company_id: Annotated[str, Field(description="Unique platform company ID of the caller.")],
    space_id: Annotated[str, Field(description="ID of the Conduct space to update.")],
    max_turns: Annotated[
        int | None,
        Field(description="Set the claude.maxTurns limit for this Conduct agent.", ge=1),
    ] = None,
    setup_patch: Annotated[
        dict[str, object] | None,
        Field(description="Keys to merge into the setup block of the harness configuration."),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
) -> unique_sdk.Module:
    """Update a Conduct space's harness configuration. Merges into the existing config."""
    try:
        return await contexts.update_conduct_config(
            upstream=upstream,
            user_id=user_id,
            company_id=company_id,
            space_id=space_id,
            max_turns=max_turns,
            setup_patch=setup_patch,
        )
    except SpaceConfigError as exc:
        raise ToolError(str(exc)) from exc
