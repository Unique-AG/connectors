from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

from polixis_mcp import contexts
from polixis_mcp.mcp.dependencies import get_upstream
from polixis_mcp.mcp.inputs.cursor import Cursor
from polixis_mcp.mcp.inputs.cursor import page_query
from polixis_mcp.mcp.inputs.cursor import PageSize
from polixis_mcp.mcp.inputs.pid import EntityPid
from polixis_mcp.upstream import Upstream


@tool(
    title="Find Flagged Parties",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("pid", "radius", "current_only", "sanctioned_only", "page_size")
async def find_flagged_parties(
    *,
    pid: EntityPid = None,
    radius: Annotated[
        int,
        Field(
            ge=1,
            le=3,
            description=(
                "Hops to look out from the entity. 1, the default, covers its own owners, "
                "directors, signatories and holdings, and fits on one page for most companies. "
                "2 reaches their ties too, but Polixis can leave parties out of a graph that "
                "large without saying so, and for a subsidiary it mostly adds the state-owned "
                "companies of its own group. Polixis stopped at 2 in every walk we tried, so 3 "
                "may find nothing more, from a much larger graph."
            ),
        ),
    ] = 1,
    current_only: Annotated[
        bool,
        Field(
            description="Only ties Polixis holds as current, leaving out former directors, "
            "shareholders and other ended relations. Polixis filters the network itself."
        ),
    ] = False,
    sanctioned_only: Annotated[
        bool,
        Field(
            description="Only sanctioned parties, filtered by Polixis itself, which makes a "
            "large network much smaller. It drops the unsanctioned parties too, so a "
            "sanctioned party reached only through one is missed; it can also find some the "
            "unfiltered network leaves out. For sanctions at any distance, with the listings, "
            "use `get_sanctions_exposure` instead."
        ),
    ] = False,
    page_size: PageSize = None,
    cursor: Cursor = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.FlaggedPartiesPage:
    """Sanctioned, PEP, state-owned and restricted parties near an organization or person,
    each with its markers and the path to it: who holds what in whom at every step.

    Polixis returns the network around the entity, both its smart graph and its full graph
    with signatories, third parties and historic ties. This MCP picks the parties whose flags
    or alerts carry a risk marker and finds a shortest path to each over Polixis's links.

    Use it for PEP and state-ownership exposure nearby; for sanctions at any distance use
    `get_sanctions_exposure`. `total_by_risk` counts every flagged party by marker across
    every page, and every page repeats it, so a question such as "is any of them
    state-owned?" is settled by a 0 there. The most severe come first: sanctioned, then PEP,
    then restricted or in a sanction-sensitive territory, then former PEP or REP, and
    state-owned last; the nearest first within each. So stop once the risks are milder than
    the question cares about.
    When `truncated_by_polixis` is true, Polixis cut the network short: do not report that
    none was found. When `next_cursor` is set, pass it back as `cursor` for the next page.
    """
    query = page_query(
        contexts.FlaggedPartiesQuery,
        cursor,
        pid=pid,
        radius=radius,
        current_only=current_only,
        sanctioned_only=sanctioned_only,
        page_size=page_size,
    )
    return await contexts.find_flagged_parties(upstream=upstream, query=query)
