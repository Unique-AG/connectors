from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.contexts.cached_calls import cached_call
from polixis_mcp.contexts.cached_calls import Freshness
from polixis_mcp.contexts.cached_calls import freshness
from polixis_mcp.contexts.formats import node_name
from polixis_mcp.contexts.formats import unique
from polixis_mcp.contexts.graph.network import Link
from polixis_mcp.contexts.graph.network import link_of
from polixis_mcp.contexts.graph.network import Party
from polixis_mcp.contexts.graph.network import party_of
from polixis_mcp.contexts.graph.network import PathStep
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import FIND_PATHS
from polixis_mcp.upstream import FindPathsRequest
from polixis_mcp.upstream import GraphPath
from polixis_mcp.upstream import NodeMeta
from polixis_mcp.upstream import PathRequestInput
from polixis_mcp.upstream import Upstream


async def find_connections(
    *, upstream: Upstream, persistence: Persistence, from_pid: str, to_pid: str
) -> Connections:
    """Polixis searches its whole graph for the path and takes no options: every request field
    besides the two ids was ignored when tried.
    """
    response = await cached_call(
        upstream=upstream,
        persistence=persistence,
        operation=FIND_PATHS,
        request=FindPathsRequest(body=PathRequestInput(source_id=from_pid, target_id=to_pid)),
    )
    meta = response.meta or {}
    paths = [
        found
        for path in response.paths or []
        if (found := _connection_path(path, start=from_pid, end=to_pid, meta=meta)) is not None
    ]
    nodes = {node.id: node for path in response.paths or [] for node in path.nodes or [] if node.id}
    on_paths = unique(
        pid for path in paths for step in path.steps for pid in (step.from_pid, step.to_pid)
    )
    return Connections(
        from_pid=from_pid,
        to_pid=to_pid,
        connected=bool(paths),
        hops=min(len(path.steps) for path in paths) if paths else None,
        paths=paths,
        parties=[
            party_of(pid=pid, node=nodes[pid], meta=meta, distance=None)
            for pid in on_paths
            if pid in nodes
        ],
        freshness=freshness(),
    )


def _connection_path(
    path: GraphPath, *, start: str, end: str, meta: dict[str, NodeMeta]
) -> ConnectionPath | None:
    """The path's links as steps from `start` to `end`, or None for a path without links.
    Polixis lists the links in no order. When they do not lead from `start` to `end`, such as
    when Polixis answers for the pid a merged one points to, the steps keep the order Polixis
    gives, so a path it found is never reported as no path.
    """
    links: list[Link] = [link for edge in path.edges or [] if (link := link_of(edge)) is not None]
    if not links:
        return None
    walked = _walk(links, start=start)
    ordered = bool(walked) and walked[-1][1] == end
    pairs = walked if ordered else _pairs_as_given(links)
    return ConnectionPath(
        ordered=ordered,
        steps=[
            PathStep(
                from_pid=here,
                from_name=node_name(meta.get(here)),
                to_pid=there,
                to_name=node_name(meta.get(there)),
                links=[
                    link for link in links if {link.source_pid, link.target_pid} == {here, there}
                ],
            )
            for here, there in pairs
        ],
    )


def _walk(links: list[Link], *, start: str) -> list[tuple[str, str]]:
    """The pairs of parties from `start`, following the links until none leads on."""
    pairs: list[tuple[str, str]] = []
    left = links
    here = start
    while touching := next(
        (link for link in left if here in (link.source_pid, link.target_pid)), None
    ):
        there = touching.target_pid if touching.source_pid == here else touching.source_pid
        pairs.append((here, there))
        left = [link for link in left if {link.source_pid, link.target_pid} != {here, there}]
        here = there
    return pairs


def _pairs_as_given(links: list[Link]) -> list[tuple[str, str]]:
    """Each pair of linked parties once, in the order and direction Polixis first gives it."""
    pairs: dict[frozenset[str], tuple[str, str]] = {}
    for link in links:
        pairs.setdefault(
            frozenset((link.source_pid, link.target_pid)), (link.source_pid, link.target_pid)
        )
    return list(pairs.values())


class ConnectionPath(BaseModel):
    """One path from the first entity to the second."""

    ordered: bool = Field(
        description="Computed by this MCP, since Polixis lists a path's links in no order: "
        "whether the steps run in order from the first entity to the second. False "
        "when Polixis's links do not lead from one to the other, such as for a merged pid: the "
        "steps then come as Polixis gives them, and still show the link it found."
    )
    steps: list[PathStep] = Field(
        description="Polixis's links on the path, put in order by this MCP when `ordered` is true."
    )


class Connections(BaseModel):
    """The paths Polixis finds between two entities."""

    from_pid: str = Field(description="The entity the path starts at.")
    to_pid: str = Field(description="The entity looked for.")
    connected: bool = Field(
        description=(
            "Computed by this MCP: whether Polixis returned a path with links. False is not "
            "proof there is none: a relation Polixis lacks can still connect them."
        )
    )
    hops: int | None = Field(
        description="Computed by this MCP: the steps on the shortest path; null when not connected."
    )
    paths: list[ConnectionPath] = Field(
        description="The paths found, usually one: the shortest Polixis knows."
    )
    parties: list[Party] = Field(
        description="Every party on the paths, with its flags; `distance` is null here."
    )
    freshness: Freshness
