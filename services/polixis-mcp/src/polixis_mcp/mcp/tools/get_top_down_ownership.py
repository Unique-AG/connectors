from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations

from polixis_mcp import contexts
from polixis_mcp.mcp.dependencies import get_persistence
from polixis_mcp.mcp.dependencies import get_upstream
from polixis_mcp.mcp.inputs.cursor import Cursor
from polixis_mcp.mcp.inputs.cursor import page_query
from polixis_mcp.mcp.inputs.cursor import PageSize
from polixis_mcp.mcp.inputs.pid import EntityPid
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import Upstream


@tool(
    title="Get Top-Down Ownership",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("pid", "page_size")
async def get_top_down_ownership(
    *,
    pid: EntityPid = None,
    page_size: PageSize = None,
    cursor: Cursor = None,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> contexts.OwnershipPage:
    """What an organization or person owns: one row per holding, however many chains of
    shareholdings reach it, with the share the entity carries in it summed over every chain,
    the chain carrying the most, and its flags.

    Polixis traces the tree down through subsidiaries and shareholding layers, and reports
    the role and share of each link only. This MCP turns the tree into rows and computes the
    effective share of each holding from the link shares. `total_by_risk` counts the flagged
    holdings of the whole group by marker, and the first page lists up to 25 of them, the
    sanctioned first; the others carry their flags on their own rows.

    Rows come largest effective share first, so the controlled subsidiaries lead and the
    minority stakes trail: stop once you have what the question needs. When `next_cursor`
    is set, pass it back as `cursor` for the next page.
    """
    query = page_query(
        contexts.OwnershipQuery,
        cursor,
        fixed={"direction": "holdings"},
        pid=pid,
        page_size=page_size,
    )
    return await contexts.get_ownership(upstream=upstream, persistence=persistence, query=query)
