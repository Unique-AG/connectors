from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import GroupId
from world_check_mcp.upstream import Upstream

PageSize = Annotated[int, Field(ge=1, le=100, description="Cases per page. LSEG allows 1 to 100.")]
PageReference = Annotated[
    str | None,
    Field(description="next_page from the previous page. Keep the same group and limit."),
]


@tool(
    title="List Cases",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def list_cases(
    group_id: GroupId,
    limit: PageSize = 25,
    page_reference: PageReference = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.CasePage:
    """List saved cases in one group, newest first.

    Pass next_page back as page_reference with the same group and limit.
    """
    return await contexts.search_cases(
        upstream=upstream, group_id=group_id, limit=limit, page_reference=page_reference
    )
