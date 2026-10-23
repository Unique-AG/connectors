from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import CaseArgument
from world_check_mcp.upstream import Upstream


@tool(
    title="Get Screening Status",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_screening_status(
    case: CaseArgument, upstream: Upstream = Depends(get_upstream)
) -> contexts.ScreeningStatus:
    """Check WATCHLIST and Passport Check progress without screening the case again."""
    try:
        return await contexts.get_screening_status(upstream=upstream, case=case)
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
