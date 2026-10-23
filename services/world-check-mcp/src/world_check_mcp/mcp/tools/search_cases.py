from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import GroupId
from world_check_mcp.upstream import Upstream

Expression = Annotated[
    str, Field(min_length=1, max_length=8000, description="LSEG FIQL expression.")
]
PageSize = Annotated[int, Field(ge=1, le=100, description="Cases per page. LSEG allows 1 to 100.")]
PageReference = Annotated[
    str | None,
    Field(description="next_page from the previous page. Keep every search criterion."),
]


@tool(
    title="Search Cases",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def search_cases(
    group_id: GroupId,
    query: Annotated[
        Expression | None, Field(description='FIQL query, such as primaryName=="Ada".')
    ] = None,
    expression: Annotated[
        Expression | None, Field(description="Extra FIQL filter. The group filter is always added.")
    ] = None,
    search_mode: Annotated[
        contexts.SearchMode,
        Field(description="DEFAULT, BEGINS_WITH, EXACT, or CONTAINS. EXACT matches a caseId."),
    ] = "DEFAULT",
    limit: PageSize = 25,
    page_reference: PageReference = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.CasePage:
    """Search saved cases in one group with LSEG FIQL, for example query primaryName=="John Smith".

    Use get_reference_data kind search_filters for the fields. Quote values that contain reserved
    characters. EXACT is the mode for an exact caseId. The group filter is always added.
    """
    return await contexts.search_cases(
        upstream=upstream,
        group_id=group_id,
        query=query,
        expression=expression,
        search_mode=search_mode,
        limit=limit,
        page_reference=page_reference,
    )
