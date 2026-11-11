import asyncio
from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.cached_calls import cached_call
from polixis_mcp.contexts.formats import node_name
from polixis_mcp.contexts.formats import unique
from polixis_mcp.contexts.formats import unix_date
from polixis_mcp.contexts.risks import ALERT_CATEGORIES_DESCRIPTION
from polixis_mcp.contexts.risks import FLAGS_DESCRIPTION
from polixis_mcp.contexts.risks import is_hidden_alert
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import GET_SMART_GRAPH
from polixis_mcp.upstream import GET_SUBGRAPH
from polixis_mcp.upstream import GetSmartGraphRequest
from polixis_mcp.upstream import GetSubgraphRequest
from polixis_mcp.upstream import NodeMeta
from polixis_mcp.upstream import SmartGraphResponse
from polixis_mcp.upstream import SubgraphRequestInput
from polixis_mcp.upstream import Upstream
from polixis_mcp.upstream import UpstreamError
from polixis_mcp.upstream import VirtualEdge
from polixis_mcp.upstream import VirtualNode
from polixis_mcp.upstream import VirtualSubgraph

GraphScope = Literal["key", "all"]


async def fetch_network(
    *, upstream: Upstream, persistence: Persistence, pid: str, radius: int, scope: GraphScope
) -> Network:
    """The network around `pid`. Only the key graph carries names, so `all` asks for both and
    names the full graph's nodes from the key one; a node only the full graph has stays unnamed.
    Polixis returns it whole, so the next page reads it from the cache. It is `truncated` when
    Polixis cut either graph short.
    """
    request = SubgraphRequestInput(id=pid, radius=radius)
    if scope == "key":
        key = await cached_call(
            upstream=upstream,
            persistence=persistence,
            operation=GET_SMART_GRAPH,
            request=GetSmartGraphRequest(body=request),
        )
        return _network(root_pid=pid, graph=key, meta=key.meta or {}, truncated=bool(key.truncated))
    try:
        async with asyncio.TaskGroup() as group:
            full = group.create_task(
                cached_call(
                    upstream=upstream,
                    persistence=persistence,
                    operation=GET_SUBGRAPH,
                    request=GetSubgraphRequest(body=request),
                )
            )
            key = group.create_task(
                cached_call(
                    upstream=upstream,
                    persistence=persistence,
                    operation=GET_SMART_GRAPH,
                    request=GetSmartGraphRequest(body=request),
                )
            )
    except* UpstreamError as errors:
        raise errors.exceptions[0] from None
    return _network(
        root_pid=pid,
        graph=full.result(),
        meta=key.result().meta or {},
        truncated=bool(full.result().truncated or key.result().truncated),
    )


def first_shortest_paths(network: Network, *, start: str) -> dict[str, list[str]]:
    """One shortest path from `start` to every party it reaches, as pids."""
    predecessors = _predecessors(network, start=start)
    paths: dict[str, list[str]] = {}
    for pid in predecessors:
        path = [pid]
        while predecessors[path[-1]]:
            path.append(predecessors[path[-1]][0])
        paths[pid] = path[::-1]
    return paths


def path_steps(network: Network, path: list[str]) -> list[PathStep]:
    between = network.links_between()
    return [
        PathStep(
            from_pid=here,
            from_name=network.name_of(here),
            to_pid=there,
            to_name=network.name_of(there),
            links=between.get(frozenset((here, there)), []),
        )
        for here, there in zip(path, path[1:], strict=False)
    ]


def _predecessors(network: Network, *, start: str) -> dict[str, list[str]]:
    """Breadth first from `start`: each reached pid's neighbours one step closer to `start`."""
    neighbours = network.neighbours()
    distance = {start: 0}
    predecessors: dict[str, list[str]] = {start: []}
    frontier = [start]
    while frontier:
        following: list[str] = []
        for pid in frontier:
            for neighbour in neighbours.get(pid, []):
                if neighbour not in distance:
                    distance[neighbour] = distance[pid] + 1
                    predecessors[neighbour] = [pid]
                    following.append(neighbour)
                elif distance[neighbour] == distance[pid] + 1:
                    predecessors[neighbour].append(pid)
        frontier = following
    return predecessors


def _network(
    *,
    root_pid: str,
    graph: SmartGraphResponse | VirtualSubgraph,
    meta: dict[str, NodeMeta],
    truncated: bool,
) -> Network:
    parties = {
        pid: party_of(
            pid=pid, node=node, meta=meta, distance=min(node.radii) if node.radii else None
        )
        for pid, node in (graph.nodes or {}).items()
    }
    links = [link for edge in graph.edges or [] if (link := link_of(edge)) is not None]
    return Network(root_pid=root_pid, parties=parties, links=links, truncated=truncated)


def party_of(
    *, pid: str, node: VirtualNode, meta: dict[str, NodeMeta], distance: int | None
) -> Party:
    return Party(
        pid=pid,
        name=node_name(meta.get(pid)),
        entity_type=node.type,
        flags=unique(node.flags or []),
        alerts=unique(name for name in node.alert_names or [] if not is_hidden_alert(name)),
        distance=distance,
    )


def link_of(edge: VirtualEdge) -> Link | None:
    if not edge.source_id or not edge.target_id:
        return None
    return Link(
        source_pid=edge.source_id,
        target_pid=edge.target_id,
        relations=[
            LinkRelation(
                role=detail.role,
                share_percent=detail.share or None,
                former=bool(detail.former),
                start_date=unix_date(detail.start_date),
                end_date=unix_date(detail.end_date),
            )
            for detail in edge.details or []
        ],
    )


class Party(BaseModel):
    """An organization or person in the network."""

    pid: str = Field(description="Its pid, for the other Polixis tools.")
    name: str | None = Field(
        description="Its name, from Polixis's smart graph; null for a party only the full "
        "graph has, which Polixis sends without names and `get_entity_profiles` can name."
    )
    entity_type: str | None = Field(
        description="PERSON or ORGANIZATION; vessels and aircraft are organizations."
    )
    flags: list[str] = Field(description=FLAGS_DESCRIPTION)
    alerts: list[str] = Field(description=ALERT_CATEGORIES_DESCRIPTION)
    distance: int | None = Field(
        description="The fewest links from the entity asked about at which Polixis reached it."
    )


class LinkRelation(BaseModel):
    """One role the link's source holds in its target."""

    role: str | None = Field(
        description="Polixis's role, such as shareholder/ founder, director, auditor or "
        "affiliated to the legal entity."
    )
    share_percent: float | None = Field(
        description="Polixis's share for the role; null when it is not reported."
    )
    former: bool = Field(description="Polixis's `former`: whether the relation has ended.")
    start_date: str | None = Field(description="YYYY-MM-DD, null if unknown.")
    end_date: str | None = Field(description="YYYY-MM-DD, null if unknown or current.")


class Link(BaseModel):
    """A link of Polixis's graph: the source holds each relation's role in the target, such as
    being its shareholder. The two parties are named where the link appears, so it carries
    their pids only.
    """

    source_pid: str = Field(description="The pid of the party holding the role.")
    target_pid: str = Field(description="The pid of the party the role is held in.")
    relations: list[LinkRelation] = Field(description="Every role the source holds in the target.")


class PathStep(BaseModel):
    """One step of a path, with every link of Polixis's graph between its two parties,
    whichever way they point.
    """

    from_pid: str = Field(description="The pid the step leaves.")
    from_name: str | None = Field(description="Its name, null when Polixis gives none.")
    to_pid: str = Field(description="The pid the step reaches.")
    to_name: str | None = Field(description="Its name, null when Polixis gives none.")
    links: list[Link] = Field(description="The links joining the two, in their own direction.")


class Network(BaseModel):
    root_pid: str
    parties: dict[str, Party]
    links: list[Link]
    truncated: bool

    def name_of(self, pid: str) -> str | None:
        party = self.parties.get(pid)
        return party.name if party is not None else None

    def neighbours(self) -> dict[str, list[str]]:
        found: dict[str, dict[str, None]] = {}
        for link in self.links:
            found.setdefault(link.source_pid, {})[link.target_pid] = None
            found.setdefault(link.target_pid, {})[link.source_pid] = None
        return {pid: list(neighbours) for pid, neighbours in found.items()}

    def links_between(self) -> dict[frozenset[str], list[Link]]:
        found: dict[frozenset[str], list[Link]] = {}
        for link in self.links:
            found.setdefault(frozenset((link.source_pid, link.target_pid)), []).append(link)
        return found
