from typing import Annotated

from fastmcp.dependencies import Depends
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
    title="Get Space Access",
    meta=_META,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def get_space_access(
    *,
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Space.SpaceAccessResponse:
    """List current access entries for the current space."""
    user_id, company_id = caller
    return await contexts.get_space_access(
        upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id
    )


@tool(
    title="Add Space Access",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=False),
)
async def add_space_access(
    *,
    access: Annotated[
        list[dict[str, object]],
        Field(
            description=(
                "Access entries to add. Each entry must have 'entityId', 'entityType' "
                "('USER' or 'GROUP'), and 'type' ('USE', 'MANAGE', or 'UPLOAD')."
            )
        ),
    ],
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Space.SpaceAccessResponse:
    """Grant access to a user or group on the current space."""
    user_id, company_id = caller
    return await contexts.add_space_access(
        upstream=upstream, user_id=user_id, company_id=company_id, space_id=space_id, access=access
    )


@tool(
    title="Delete Space Access",
    meta=_META,
    annotations=ToolAnnotations(idempotent_hint=True),
)
async def delete_space_access(
    *,
    access_ids: Annotated[
        list[str],
        Field(description="List of access entry IDs to remove."),
    ],
    upstream: Upstream = Depends(get_upstream),
    caller: tuple[str, str] = Depends(get_caller),
    space_id: str = Depends(get_space_id),
) -> unique_sdk.Space.DeleteSpaceAccessResponse:
    """Revoke access entries from the current space."""
    user_id, company_id = caller
    return await contexts.delete_space_access(
        upstream=upstream,
        user_id=user_id,
        company_id=company_id,
        space_id=space_id,
        access_ids=access_ids,
    )
