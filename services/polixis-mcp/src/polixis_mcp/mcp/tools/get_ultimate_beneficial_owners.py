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
    title="Get Ultimate Beneficial Owners",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("pid", "page_size")
async def get_ultimate_beneficial_owners(
    *,
    pid: EntityPid = None,
    page_size: PageSize = None,
    cursor: Cursor = None,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> contexts.OwnershipPage:
    """Who owns an organization: one row per owner, however many chains of shareholdings
    reach it, with the share it carries in the organization summed over every chain, the
    chain carrying the most, and its flags. Polixis reports only the share on each link: this
    MCP computes the effective share from them. `total_by_risk` counts the flagged owners of the
    whole tree by marker, and the first page lists up to 25 of them, the sanctioned first; the
    others carry their flags on their own rows.

    Rows come largest effective share first, so a threshold question such as "who holds 25%
    or more" is settled once the shares fall below it: stop there rather than reading every
    page, unless `total_share_unknown` counts owners not yet read, whose share may be higher.
    When `next_cursor` is set, pass it back as `cursor` for the next page.
    """
    query = page_query(
        contexts.OwnershipQuery, cursor, pid=pid, direction="owners", page_size=page_size
    )
    return await contexts.get_ownership(upstream=upstream, persistence=persistence, query=query)
