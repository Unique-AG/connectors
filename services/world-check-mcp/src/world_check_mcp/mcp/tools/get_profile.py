from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import ReferenceId
from world_check_mcp.upstream import Upstream


@tool(
    title="Get Profile",
    description=(
        "Get the World-Check record for a match: its names and categories.\n"
        "\n"
        "Pass the match's referenceId, not its resultId."
    ),
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("reference_id")
async def get_profile(
    reference_id: ReferenceId, upstream: Upstream = Depends(get_upstream)
) -> contexts.Profile:
    return await contexts.get_profile(upstream=upstream, reference_id=reference_id)
