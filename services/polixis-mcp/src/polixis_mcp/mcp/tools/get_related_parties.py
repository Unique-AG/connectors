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
from polixis_mcp.mcp.inputs.pid import EntityPid
from polixis_mcp.upstream import Upstream


@tool(
    title="Get Related Parties",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("pid", "categories", "page_size")
async def get_related_parties(
    *,
    pid: EntityPid = None,
    categories: Annotated[
        list[contexts.RelationCategory] | None,
        Field(
            min_length=1,
            description=(
                "The kinds of relation to return, as Polixis names them: board (the board of "
                "directors and equivalent roles; for a person, the supervisory boards they sit "
                "on), executiveSenior (management board members and other high-ranking roles), "
                "executive (other executive roles, such as department heads or secretaries), "
                "political (public administration roles, such as members of parliament), "
                "signature (signatories), shareholdingInformation (its shareholders, indirect "
                "shareholders and beneficial owners), ownershipInOtherEntities (its "
                "subsidiaries, branches and holdings), thirdParty (service providers, such as "
                "auditors and liquidators, or for a person the organizations they work for) and "
                "membership. Polixis warns that registers use board, executiveSenior, executive "
                "and political differently, so ask for all four when looking for directors or "
                "managers. Leave it out for all of them."
            ),
        ),
    ] = None,
    page_size: Annotated[
        int,
        Field(
            ge=1,
            le=45,
            description="Related parties per page, at most 45. Polixis pages them itself; the "
            "default of 40 comes to about 7,000 tokens.",
        ),
    ] = 40,
    cursor: Cursor = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.RelatedPartiesPage:
    """The directors, executives, signatories, shareholders, holdings and other parties
    related to an organization or person, with their roles, shares, dates, sources and flags.

    Polixis pages them itself: when `next_cursor` is set, pass it back as `cursor` for the
    next page. For the shares carried through several layers of owners, use
    `get_ultimate_beneficial_owners` instead.
    """
    query = page_query(
        contexts.RelatedPartiesQuery,
        cursor,
        pid=pid,
        categories=tuple(categories) if categories else None,
        page_size=page_size,
    )
    return await contexts.get_related_parties(upstream=upstream, query=query)
