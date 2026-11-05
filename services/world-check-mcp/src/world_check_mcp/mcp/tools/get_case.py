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
    title="Get Case",
    description=(
        "Get a saved case by its internal caseSystemId or its exact external caseId.\n"
        "\n"
        "An internal id is tried first. Use the returned case_system_id with the other case "
        "tools."
    ),
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("case")
async def get_case(
    case: CaseArgument, upstream: Upstream = Depends(get_upstream)
) -> contexts.CaseDetails:
    try:
        return await contexts.get_case(upstream=upstream, case=case)
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
