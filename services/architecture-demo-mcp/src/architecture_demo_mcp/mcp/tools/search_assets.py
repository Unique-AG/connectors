from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from architecture_demo_mcp.contexts import assets
from architecture_demo_mcp.mcp.dependencies import get_upstream
from architecture_demo_mcp.upstream import Upstream


@tool(
    title="Search Assets",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def search_assets(
    query: Annotated[
        str, Field(min_length=1, description="A ticker or words from the company or fund name.")
    ],
    limit: Annotated[int, Field(ge=1, le=100, description="The most matches to return.")] = 10,
    upstream: Upstream = Depends(get_upstream),
) -> list[assets.AssetMatch]:
    """Find stocks, ETFs and mutual funds by ticker or name.

    Each match carries the `ticker` every other tool takes.
    """
    return await assets.search_assets(upstream=upstream, query=query, limit=limit)
