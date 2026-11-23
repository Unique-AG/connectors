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
    title="Find Linked Companies",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("pid", "radius", "scope", "page_size")
async def find_linked_companies(
    *,
    pid: EntityPid = None,
    radius: Annotated[
        int,
        Field(
            ge=2,
            le=3,
            description=(
                "Links out from the entity to look. 2 finds the companies tied to it directly "
                "or through one person; 3 also those tied through two people in a row, such as a "
                "relative's business partner. Polixis documents no maximum and stopped at 2 in "
                "every walk we tried, so 3 may find nothing more, from a much larger graph."
            ),
        ),
    ] = 2,
    scope: Annotated[
        contexts.GraphScope,
        Field(
            description=(
                "`key` for ownership, management and family ties, with every company named; "
                "`all` adds signatories, third parties and historic ties, whose companies may "
                "come without a name."
            )
        ),
    ] = "key",
    page_size: PageSize = None,
    cursor: Cursor = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.LinkedCompaniesPage:
    """Companies an organization or person is tied to: directly, as owner, director, signatory
    or subsidiary, or through people in between, such as a PEP's relative or associate, or a
    director or owner the company shares with it. Each comes with the chains of people and the
    links that tie it, and its flags.

    Polixis returns the network around the entity: with `scope` key its smart graph, which
    leaves out signatory, third-party and historic relations, and with `all` its full graph
    too. This MCP finds the companies in it and the chains of people that tie each one.

    The nearest come first, then the flagged, then those tied through the most people, so the
    first page usually answers the question, and `total_by_risk` counts the flagged companies
    by marker. When `truncated_by_polixis` is true, Polixis cut the network short, so more
    companies may exist. Start with `radius` 2 and widen to 3 only when the
    question needs ties further out. For what an entity owns down the chain use
    `get_top_down_ownership`; for sanctioned, PEP or state-owned parties
    `find_flagged_parties`. When `next_cursor` is set, pass it back as `cursor`.
    """
    query = page_query(
        contexts.LinkedCompaniesQuery,
        cursor,
        pid=pid,
        radius=radius,
        scope=scope,
        page_size=page_size,
    )
    return await contexts.find_linked_companies(upstream=upstream, query=query)
