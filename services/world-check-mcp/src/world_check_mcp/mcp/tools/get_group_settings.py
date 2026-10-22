from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import GroupId
from world_check_mcp.upstream import Upstream


@tool(
    title="Get Group Settings",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_group_settings(
    group_id: GroupId, upstream: Upstream = Depends(get_upstream)
) -> contexts.GroupSettings:
    """Get one group's case template and resolution toolkit.

    Secondary field type ids and resolution ids are group-specific. Read them before screening
    or resolving a match.
    """
    return await contexts.get_group_settings(upstream=upstream, group_id=group_id)
