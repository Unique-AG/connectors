from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import ExternalCaseId
from world_check_mcp.upstream import Upstream


@tool(
    title="Get Case Reference",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_case_reference(
    case_id: ExternalCaseId, upstream: Upstream = Depends(get_upstream)
) -> contexts.CaseReferenceDetails:
    """Translate an external caseId into the internal caseSystemId the other tools use."""
    try:
        return await contexts.get_case_reference(upstream=upstream, case_id=case_id)
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
