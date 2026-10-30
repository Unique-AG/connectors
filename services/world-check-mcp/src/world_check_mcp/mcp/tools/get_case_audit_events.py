from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import CaseArgument
from world_check_mcp.upstream import Upstream

PageSize = Annotated[int, Field(ge=1, le=250, description="Events per page, at most 250.")]
PageReference = Annotated[
    str | None, Field(description="next_page from the previous page. Keep the query and limit.")
]
Query = Annotated[
    str,
    Field(
        min_length=1,
        max_length=8000,
        description="Optional FIQL query. Without eventDate, LSEG returns the last seven days.",
    ),
]


@tool(
    title="Get Case Audit Events",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_case_audit_events(
    case: CaseArgument,
    query: Annotated[
        Query | None,
        Field(description="Optional FIQL query. Without eventDate, the last seven days."),
    ] = None,
    limit: PageSize = 25,
    page_reference: PageReference = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.AuditPage:
    """Read audit events for one case, newest first, including passport verification decisions.

    This does not record an audit action.
    """
    try:
        return await contexts.get_case_audit_events(
            upstream=upstream, case=case, query=query, limit=limit, page_reference=page_reference
        )
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
