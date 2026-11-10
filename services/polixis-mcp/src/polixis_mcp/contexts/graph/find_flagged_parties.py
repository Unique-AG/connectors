from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.graph.network import fetch_network
from polixis_mcp.contexts.graph.network import first_shortest_paths
from polixis_mcp.contexts.graph.network import Party
from polixis_mcp.contexts.graph.network import path_steps
from polixis_mcp.contexts.graph.network import PathStep
from polixis_mcp.contexts.pages import encode_cursor
from polixis_mcp.contexts.pages import page_of
from polixis_mcp.contexts.pages import PageQuery
from polixis_mcp.contexts.risks import risk_counts
from polixis_mcp.contexts.risks import RISK_COUNTS_DESCRIPTION
from polixis_mcp.contexts.risks import risk_markers
from polixis_mcp.contexts.risks import RISK_MARKERS_DESCRIPTION
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import Upstream


async def find_flagged_parties(
    *, upstream: Upstream, persistence: Persistence, query: FlaggedPartiesQuery
) -> FlaggedPartiesPage:
    """Nearest first; among equally near ones the sanctioned first, then by name, unnamed last."""
    network = await fetch_network(
        upstream=upstream, persistence=persistence, pid=query.pid, radius=query.radius, scope="all"
    )
    paths = first_shortest_paths(network, start=query.pid)
    flagged = sorted(
        (
            FlaggedParty(party=party, risks=risks, path=path_steps(network, paths[pid]))
            for pid, party in network.parties.items()
            if pid != query.pid
            and pid in paths
            and (risks := risk_markers(flags=party.flags, alerts=party.alerts))
        ),
        key=lambda found: (
            len(found.path),
            "SANCTION" not in found.risks,
            found.party.name is None,
            found.party.name or "",
            found.party.pid,
        ),
    )
    page, next_offset = page_of(flagged, offset=query.offset, size=query.page_size)
    return FlaggedPartiesPage(
        pid=query.pid,
        parties_checked=sum(1 for pid in network.parties if pid != query.pid),
        truncated_by_polixis=network.truncated,
        total_flagged=len(flagged),
        total_by_risk=risk_counts(found.risks for found in flagged),
        flagged=page,
        next_cursor=(
            encode_cursor(query.model_copy(update={"offset": next_offset}))
            if next_offset is not None
            else None
        ),
    )


class FlaggedPartiesQuery(PageQuery):
    pid: str = Field(min_length=1)
    radius: int = Field(default=2, ge=1, le=3)
    page_size: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class FlaggedParty(BaseModel):
    """A party near the entity that carries a sanctions, PEP or state-ownership marker."""

    party: Party = Field(description="The flagged party.")
    risks: list[str] = Field(description=RISK_MARKERS_DESCRIPTION)
    path: list[PathStep] = Field(
        description="One shortest path from the entity to the party, with the roles at each step."
    )


class FlaggedPartiesPage(BaseModel):
    """The flagged parties in the network around an entity, one page of them."""

    pid: str = Field(description="The entity the walk started at.")
    parties_checked: int = Field(description="Parties in the network, the entity left out.")
    truncated_by_polixis: bool = Field(
        description=(
            "Whether Polixis cut the network short, so parties beyond what it returned are "
            "missing. When true, a count of 0 does not show that none exists: say the network "
            "was cut, rather than that none was found."
        )
    )
    total_flagged: int = Field(description="Flagged parties across every page.")
    total_by_risk: dict[str, int] = Field(description=RISK_COUNTS_DESCRIPTION)
    flagged: list[FlaggedParty] = Field(description="The flagged parties of this page.")
    next_cursor: str | None = Field(
        description="Pass it as `cursor` for the next page; null on the last page."
    )
