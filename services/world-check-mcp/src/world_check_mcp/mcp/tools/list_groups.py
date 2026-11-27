from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_cache
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.persistence import Cache
from world_check_mcp.upstream import Upstream

PageSize = Annotated[int, Field(ge=1, le=100, description="Groups per page.")]


@tool(
    title="List Groups",
    description=(
        "List the LSEG groups this service account can screen in, including descendant "
        "groups, a page at a time.\n"
        "\n"
        "Call it before screening, then pass a group id to `get_group_settings`. Pass a few "
        "words of the group's name as query, or a parent_id for the groups directly under one. "
        "Pass next_page back as page_reference with the same query and parent_id."
    ),
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("parent_id", "limit", "page_reference")
async def list_groups(
    query: Annotated[
        str | None,
        Field(min_length=1, max_length=200, description="Words of the group name. Typos match."),
    ] = None,
    parent_id: Annotated[
        str | None, Field(min_length=1, description="Only the groups directly under this group.")
    ] = None,
    limit: PageSize = 25,
    *,
    page_reference: Annotated[
        str | None,
        Field(description="next_page from the previous page. Keep the same query and parent_id."),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
    cache: Cache = Depends(get_cache),
) -> contexts.GroupPage:
    try:
        return await contexts.list_groups(
            upstream=upstream,
            cache=cache,
            query=query,
            parent_id=parent_id,
            limit=limit,
            page_reference=page_reference,
        )
    except contexts.GroupPageError as error:
        raise ToolError(str(error)) from error
