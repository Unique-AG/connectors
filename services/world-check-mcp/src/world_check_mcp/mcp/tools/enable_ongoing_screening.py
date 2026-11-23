from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import CaseArgument
from world_check_mcp.upstream import Upstream


@tool(
    title="Enable Ongoing Screening",
    description=(
        "Enable WATCHLIST monitoring for one case.\n"
        "\n"
        "This changes the case's screening state. LSEG can answer 200 without enabling it, so "
        "read enabled in the result: false means monitoring is off, and failures says why. "
        "Media Check is not enabled."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, idempotent_hint=True, destructive_hint=False, open_world_hint=True
    ),
)
@trace_arguments("case")
async def enable_ongoing_screening(
    case: CaseArgument, upstream: Upstream = Depends(get_upstream)
) -> contexts.OngoingScreening:
    try:
        return await contexts.enable_ongoing_screening(upstream=upstream, case=case)
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
