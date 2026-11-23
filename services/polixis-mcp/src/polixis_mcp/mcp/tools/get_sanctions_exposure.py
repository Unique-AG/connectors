from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations

from polixis_mcp import contexts
from polixis_mcp.mcp.dependencies import get_upstream
from polixis_mcp.mcp.inputs.cursor import Cursor
from polixis_mcp.mcp.inputs.cursor import page_query
from polixis_mcp.mcp.inputs.cursor import PageSize
from polixis_mcp.mcp.inputs.pid import EntityPid
from polixis_mcp.upstream import Upstream


@tool(
    title="Get Sanctions Exposure",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("pid", "page_size")
async def get_sanctions_exposure(
    *,
    pid: EntityPid = None,
    page_size: PageSize = None,
    cursor: Cursor = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.SanctionsExposurePage:
    """An organization's or person's own sanctions listings, and every sanctioned party
    Polixis relates to it at any distance, each with its lists, programmes and the relations
    that lead to it: who holds what in whom at every step. Polixis walks its graph and
    returns each sanctioned party with the relations that lead to it; this MCP ranks them and
    counts the hops.

    Use it for direct and indirect sanctions exposure; for PEP or state-owned parties nearby
    use `find_flagged_parties`. The nearest come first. When `next_cursor` is set, pass it
    back as `cursor`.
    Polixis does not document this route yet, so its answers may change without notice.
    """
    query = page_query(contexts.SanctionsExposureQuery, cursor, pid=pid, page_size=page_size)
    return await contexts.get_sanctions_exposure(upstream=upstream, query=query)
