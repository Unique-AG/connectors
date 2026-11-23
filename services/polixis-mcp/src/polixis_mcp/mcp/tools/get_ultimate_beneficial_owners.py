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
) -> contexts.OwnershipPage:
    """Who owns or controls an organization: one row per owner, however many chains reach it,
    with the share it carries in the organization summed over every chain, the chain carrying
    the most, and its flags.

    Polixis traces the tree up through shareholders and control layers to the last owners,
    and reports the role and share of each link only. This MCP turns the tree into rows and
    computes each owner's effective share from the link shares; a controlling person whose
    links carry no share gets none. `total_by_risk` counts the flagged owners of the whole
    tree by marker, and the first page lists up to 25 of them, the sanctioned first; the
    others carry their flags on their own rows.

    Rows come largest effective share first, so a threshold question such as "who holds 25%
    or more" is settled once the shares fall below it: stop there rather than reading every
    page, unless `total_share_unknown` counts owners not yet read, whose share may be higher.
    When `next_cursor` is set, pass it back as `cursor` for the next page.
    """
    query = page_query(
        contexts.OwnershipQuery,
        cursor,
        fixed={"direction": "owners"},
        pid=pid,
        page_size=page_size,
    )
    return await contexts.get_ownership(upstream=upstream, query=query)
