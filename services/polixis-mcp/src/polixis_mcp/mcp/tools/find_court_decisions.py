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
    title="Find Court Decisions",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("pid", "page_size")
async def find_court_decisions(
    *,
    pid: EntityPid = None,
    page_size: PageSize = None,
    cursor: Cursor = None,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> contexts.CourtDecisionsPage:
    """Court decisions that name an organization or person, or one of its related parties:
    court, country, year and the passages naming them, without the full text, which
    `get_court_decision` returns for one decision.

    Those naming the entity itself come first, then the newest. When `next_cursor` is set,
    pass it back as `cursor`. A wrong pid also returns no decisions, so check the pid before
    reporting a clean result.
    Polixis does not document this route yet, so its answers may change without notice.
    """
    query = page_query(contexts.CourtDecisionsQuery, cursor, pid=pid, page_size=page_size)
    return await contexts.find_court_decisions(
        upstream=upstream, persistence=persistence, query=query
    )
