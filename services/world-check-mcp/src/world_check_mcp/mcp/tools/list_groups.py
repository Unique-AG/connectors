from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.upstream import Upstream


@tool(
    title="List Groups",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def list_groups(upstream: Upstream = Depends(get_upstream)) -> list[contexts.Group]:
    """List the LSEG groups this service account can screen in, including descendant groups.

    Call it before screening, then pass a group id to `get_group_settings`.
    """
    return await contexts.list_groups(upstream=upstream)
