from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import ReferenceId
from world_check_mcp.upstream import Upstream


@tool(
    title="Get Profile",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_profile(
    reference_id: ReferenceId, upstream: Upstream = Depends(get_upstream)
) -> contexts.Profile:
    """Get the World-Check record for a match: its names and categories.

    Pass the match's referenceId, not its resultId.
    """
    return await contexts.get_profile(upstream=upstream, reference_id=reference_id)
