from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

from polixis_mcp import contexts
from polixis_mcp.contexts import PID_PATTERN
from polixis_mcp.mcp.dependencies import get_upstream
from polixis_mcp.upstream import Upstream


@tool(
    title="Get Entity Profiles",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments(lambda arguments: {"pid_count": len(arguments["pids"])})
async def get_entity_profiles(
    *,
    pids: Annotated[
        list[Annotated[str, Field(pattern=PID_PATTERN)]],
        Field(
            min_length=1,
            max_length=10,
            description=(
                "The pids to look up, up to 10, such as every owner in a tree at once. A pid "
                "the user gave goes to `resolve_permanent_id` first."
            ),
        ),
    ],
    sections: Annotated[
        list[contexts.ProfileSection] | None,
        Field(
            min_length=1,
            description=(
                "The parts of each profile to return. Leave it out for the key identifiers: "
                "name records, identifiers, countries, dates, flags, alerts and sanction "
                "statuses. Ask for `sanctions` for each listing's programme, listing and "
                "delisting dates, reference number and designation details, and `positions` for "
                "the offices a PEP holds or held, with their institutions and dates."
            ),
        ),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.EntityProfiles:
    """Profiles of up to 10 organizations or people at once: names, identifiers, dates,
    countries, sanctions and PEP flags, alerts, sanctions listings and positions held.

    Use it to screen or tell apart entities another tool returned by `pid`, in one call
    rather than one per entity. A pid Polixis does not know comes back with `rejected` set.
    `sanctions` and `positions` make each profile several times larger, so ask for fewer pids
    with them.
    """
    return await contexts.get_entity_profiles(upstream=upstream, pids=pids, sections=sections)
