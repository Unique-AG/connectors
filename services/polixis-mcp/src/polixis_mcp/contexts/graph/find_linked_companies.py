from itertools import pairwise

from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.graph.network import fetch_network
from polixis_mcp.contexts.graph.network import GraphScope
from polixis_mcp.contexts.graph.network import Link
from polixis_mcp.contexts.graph.network import Network
from polixis_mcp.contexts.graph.network import Party
from polixis_mcp.contexts.pages import encode_cursor
from polixis_mcp.contexts.pages import page_of
from polixis_mcp.contexts.pages import PageQuery
from polixis_mcp.contexts.pages import QueryPid
from polixis_mcp.contexts.pages import snapshot_for
from polixis_mcp.contexts.risks import risk_counts
from polixis_mcp.contexts.risks import RISK_COUNTS_DESCRIPTION
from polixis_mcp.contexts.risks import risk_markers
from polixis_mcp.contexts.risks import RISK_MARKERS_DESCRIPTION
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import Upstream

_THROUGH_SHOWN = 5


async def find_linked_companies(
    *, upstream: Upstream, persistence: Persistence, query: LinkedCompaniesQuery
) -> LinkedCompaniesPage:
    """Companies tied to the entity directly, or through people in a row, at most `radius`
    links away: a relative or associate of a person, a director or owner of a company. The
    nearest come first, then the flagged, then those reached through the most people.
    """
    network = await fetch_network(
        upstream=upstream,
        persistence=persistence,
        pid=query.pid,
        radius=query.radius,
        scope=query.scope,
    )
    companies = sorted(
        _linked_companies(network, pid=query.pid, radius=query.radius),
        key=lambda found: (
            found.hops,
            not found.risks,
            -found.through_total,
            found.company.name is None,
            found.company.name or "",
            found.company.pid,
        ),
    )
    snapshot = snapshot_for(query, companies)
    page, next_offset = page_of(companies, offset=query.offset, size=query.page_size)
    return LinkedCompaniesPage(
        pid=query.pid,
        total_companies=len(companies),
        total_direct=sum(1 for found in companies if found.direct_links),
        total_flagged=sum(1 for found in companies if found.risks),
        total_by_risk=risk_counts(found.risks for found in companies),
        truncated_by_polixis=network.truncated,
        companies=page,
        next_cursor=(
            encode_cursor(query.model_copy(update={"offset": next_offset, "snapshot": snapshot}))
            if next_offset is not None
            else None
        ),
    )


def _linked_companies(network: Network, *, pid: str, radius: int) -> list[LinkedCompany]:
    between = network.links_between()
    neighbours = network.neighbours()

    def links(one: str, other: str) -> list[Link]:
        return between.get(frozenset((one, other)), [])

    through: dict[str, list[PersonChain]] = {}
    for person, chain in _people_chains(network, pid=pid, longest=radius - 1).items():
        for company in neighbours.get(person, []):
            if company != pid:
                stops = [pid, *chain, company]
                through.setdefault(company, []).append(
                    PersonChain(
                        people=[
                            PersonOnChain(pid=step, name=network.name_of(step)) for step in chain
                        ],
                        links=[
                            link for one, other in pairwise(stops) for link in links(one, other)
                        ],
                    )
                )
    return [
        _linked_company(company, direct_links=links(pid, other), chains=through.get(other, []))
        for other in {*neighbours.get(pid, []), *through}
        if (company := network.parties.get(other)) is not None
        and company.entity_type == "ORGANIZATION"
    ]


def _linked_company(
    company: Party, *, direct_links: list[Link], chains: list[PersonChain]
) -> LinkedCompany:
    return LinkedCompany(
        company=company,
        risks=risk_markers(flags=company.flags, alerts=company.alerts),
        hops=1 if direct_links else 1 + min(len(chain.people) for chain in chains),
        direct_links=direct_links,
        through_total=len(chains),
        through=sorted(chains, key=lambda chain: len(chain.people))[:_THROUGH_SHOWN],
    )


def _people_chains(network: Network, *, pid: str, longest: int) -> dict[str, list[str]]:
    """Every person tied to the entity through at most `longest` people in a row, with the
    shortest such chain of pids, from the person next to the entity to them.
    """
    neighbours = network.neighbours()
    chains: dict[str, list[str]] = {}
    frontier: list[list[str]] = [[]]
    for _ in range(longest):
        following: list[list[str]] = []
        for chain in frontier:
            for person in neighbours.get(chain[-1] if chain else pid, []):
                party = network.parties.get(person)
                if (
                    person != pid
                    and person not in chains
                    and party is not None
                    and party.entity_type == "PERSON"
                ):
                    chains[person] = [*chain, person]
                    following.append(chains[person])
        frontier = following
    return chains


class LinkedCompaniesQuery(PageQuery):
    pid: QueryPid
    radius: int = Field(default=2, ge=2, le=3)
    scope: GraphScope = "key"
    page_size: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class PersonOnChain(BaseModel):
    """A person on the way from the entity to the company."""

    pid: str = Field(description="The person's pid.")
    name: str | None = Field(description="Their name, null when Polixis gives none.")


class PersonChain(BaseModel):
    """People in a row through whom the entity is tied to the company, found by this MCP."""

    people: list[PersonOnChain] = Field(
        description="The people in order, from the one tied to the entity to the one tied to "
        "the company."
    )
    links: list[Link] = Field(
        description="The links along the chain in order, from the entity to the company, each "
        "in its own direction."
    )


class LinkedCompany(BaseModel):
    """A company tied to the entity, and how, as this MCP found it in Polixis's network."""

    company: Party = Field(description="The company, with its flags and distance.")
    risks: list[str] = Field(description=RISK_MARKERS_DESCRIPTION)
    hops: int = Field(
        description="Computed by this MCP: links between the entity and the company; 1 is direct."
    )
    direct_links: list[Link] = Field(
        description="Polixis's links between the entity and the company; empty when they are "
        "tied only through people."
    )
    through_total: int = Field(
        description="Computed by this MCP: how many people next to the company tie it to the "
        "entity."
    )
    through: list[PersonChain] = Field(
        description=f"Computed by this MCP: the shortest {_THROUGH_SHOWN} chains of people, "
        "with Polixis's links along each."
    )


class LinkedCompaniesPage(BaseModel):
    """The companies tied to an entity, one page of them."""

    pid: str = Field(description="The entity asked about.")
    total_companies: int = Field(description="Computed by this MCP: companies across every page.")
    total_direct: int = Field(
        description="Computed by this MCP: companies tied to the entity directly."
    )
    total_flagged: int = Field(description="Computed by this MCP: companies with a risk marker.")
    total_by_risk: dict[str, int] = Field(description=RISK_COUNTS_DESCRIPTION)
    truncated_by_polixis: bool = Field(
        description=(
            "Polixis's `truncated`: whether it cut the network short, so companies beyond "
            "what it returned are missing. When true, a count of 0 does not show that none "
            "exists: say the network was cut, rather than that none was found."
        )
    )
    companies: list[LinkedCompany] = Field(
        description="The companies of this page: the nearest first, then the flagged, then "
        "those tied through the most people."
    )
    next_cursor: str | None = Field(
        description="Pass it as `cursor` for the next page; null on the last page."
    )
