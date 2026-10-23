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

PageSize = Annotated[int, Field(ge=1, le=100, description="Matches per page.")]
PageReference = Annotated[
    str | None,
    Field(description="next_page from the previous page. Keep the case, filter, and limit."),
]
Expression = Annotated[
    str,
    Field(
        min_length=1,
        max_length=8000,
        description="Optional FIQL filter, such as matchStrength==EXACT.",
    ),
]


@tool(
    title="Get Case Results",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_case_results(
    case: CaseArgument,
    limit: PageSize = 50,
    page_reference: PageReference = None,
    expression: Annotated[
        Expression | None, Field(description="Optional FIQL filter, such as matchStrength==EXACT.")
    ] = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.CaseResults:
    """Get paginated match facts by internal caseSystemId or exact external caseId.

    reference_id identifies a profile. result_id identifies the match on this case.
    """
    try:
        return await contexts.get_case_results(
            upstream=upstream,
            case=case,
            limit=limit,
            page_reference=page_reference,
            expression=expression,
        )
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
