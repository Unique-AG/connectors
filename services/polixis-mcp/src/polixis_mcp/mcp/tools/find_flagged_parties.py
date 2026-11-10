from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

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
    title="Find Flagged Parties",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("pid", "radius", "page_size")
async def find_flagged_parties(
    *,
    pid: EntityPid = None,
    radius: Annotated[
        int,
        Field(
            ge=1,
            le=3,
            description=(
                "Hops to look out from the entity. Polixis documents no maximum and stopped at 2 "
                "in every walk we tried, so 3 may find nothing more, from a much larger graph."
            ),
        ),
    ] = 2,
    page_size: PageSize = None,
    cursor: Cursor = None,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> contexts.FlaggedPartiesPage:
    """Sanctioned, PEP, state-owned and restricted parties near an organization or person,
    each with its markers and the path to it: who holds what in whom at every step.

    Use it for PEP and state-ownership exposure nearby; for sanctions at any distance use
    `get_sanctions_exposure`. `total_by_risk` counts every flagged party by marker on each
    page, so a question such as "is any of them state-owned?" is settled by a 0 there. The
    nearest come first, the sanctioned before the others at the same distance, so stop once
    they are farther than the question cares about. When `truncated_by_polixis` is true,
    Polixis cut the network short: do not report that none was found. When `next_cursor` is
    set, pass it back as `cursor` for the next page.
    """
    query = page_query(
        contexts.FlaggedPartiesQuery, cursor, pid=pid, radius=radius, page_size=page_size
    )
    return await contexts.find_flagged_parties(
        upstream=upstream, persistence=persistence, query=query
    )
