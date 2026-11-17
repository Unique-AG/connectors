from collections.abc import Iterator

from polixis_mcp.contexts.cached_calls import cached_call
from polixis_mcp.contexts.formats import node_name
from polixis_mcp.contexts.formats import unique
from polixis_mcp.contexts.ownership.get_ownership.inputs import OwnershipQuery
from polixis_mcp.contexts.ownership.get_ownership.outputs import ChainLink
from polixis_mcp.contexts.ownership.get_ownership.outputs import FLAGGED_SHOWN
from polixis_mcp.contexts.ownership.get_ownership.outputs import OwnershipEntity
from polixis_mcp.contexts.ownership.get_ownership.outputs import OwnershipFlag
from polixis_mcp.contexts.ownership.get_ownership.outputs import OwnershipPage
from polixis_mcp.contexts.pages import encode_cursor
from polixis_mcp.contexts.pages import page_of
from polixis_mcp.contexts.risks import is_hidden_alert
from polixis_mcp.contexts.risks import risk_counts
from polixis_mcp.contexts.risks import risk_markers
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import GET_TOP_DOWN_OWNERSHIP
from polixis_mcp.upstream import GET_ULTIMATE_BENEFICIAL_OWNERS
from polixis_mcp.upstream import GetTopDownOwnershipPath
from polixis_mcp.upstream import GetTopDownOwnershipRequest
from polixis_mcp.upstream import GetUltimateBeneficialOwnersPath
from polixis_mcp.upstream import GetUltimateBeneficialOwnersRequest
from polixis_mcp.upstream import NodeMeta
from polixis_mcp.upstream import UboNode
from polixis_mcp.upstream import UboResult
from polixis_mcp.upstream import Upstream

type _Chain = tuple[UboNode, ...]


async def get_ownership(
    *, upstream: Upstream, persistence: Persistence, query: OwnershipQuery
) -> OwnershipPage:
    """One row per entity, however many chains reach it, the largest effective share first, so
    a threshold question is answered once the shares drop below it. The flagged entities come
    sanctioned first, then in the order of the rows. Polixis returns the whole tree at once, so
    the next page reads it from the cache.
    """
    tree = await _tree(upstream=upstream, persistence=persistence, query=query)
    meta = tree.meta or {}
    chains_by_pid: dict[str, list[_Chain]] = {}
    for chain in _chains(tree.roots or [], above=()):
        if pid := chain[-1].id:
            chains_by_pid.setdefault(pid, []).append(chain)
    entities = sorted(
        (_entity(pid=pid, chains=chains, meta=meta) for pid, chains in chains_by_pid.items()),
        key=lambda entity: (
            entity.effective_share_percent is None,
            -(entity.effective_share_percent or 0.0),
            entity.depth,
            entity.name is None,
            entity.name or "",
            entity.pid,
        ),
    )
    flagged = sorted(
        (
            OwnershipFlag(
                pid=entity.pid,
                name=entity.name,
                effective_share_percent=entity.effective_share_percent,
                depth=entity.depth,
                risks=risks,
            )
            for entity in entities
            if (risks := risk_markers(flags=entity.flags, alerts=entity.alerts))
        ),
        key=lambda flag: "SANCTION" not in flag.risks,
    )
    page, next_offset = page_of(entities, offset=query.offset, size=query.page_size)
    return OwnershipPage(
        pid=query.pid,
        total_entities=len(entities),
        total_share_unknown=sum(1 for entity in entities if entity.share_unknown_on_some_chain),
        truncated_by_polixis=bool(tree.truncated),
        total_flagged=len(flagged),
        total_by_risk=risk_counts(flag.risks for flag in flagged),
        flagged=flagged[:FLAGGED_SHOWN] if query.offset == 0 else [],
        entities=page,
        next_cursor=(
            encode_cursor(query.model_copy(update={"offset": next_offset}))
            if next_offset is not None
            else None
        ),
    )


async def _tree(
    *, upstream: Upstream, persistence: Persistence, query: OwnershipQuery
) -> UboResult:
    if query.direction == "owners":
        return await cached_call(
            upstream=upstream,
            persistence=persistence,
            operation=GET_ULTIMATE_BENEFICIAL_OWNERS,
            request=GetUltimateBeneficialOwnersRequest(
                path=GetUltimateBeneficialOwnersPath(id=query.pid)
            ),
        )
    return await cached_call(
        upstream=upstream,
        persistence=persistence,
        operation=GET_TOP_DOWN_OWNERSHIP,
        request=GetTopDownOwnershipRequest(path=GetTopDownOwnershipPath(id=query.pid)),
    )


def _chains(nodes: list[UboNode], *, above: _Chain) -> Iterator[_Chain]:
    """Every chain of links from the entity asked about to a node of the tree. A node without an
    id gets no row of its own, but the chains through it still reach the nodes below.
    """
    for node in nodes:
        chain = (*above, node)
        yield chain
        yield from _chains(node.children or [], above=chain)


def _entity(*, pid: str, chains: list[_Chain], meta: dict[str, NodeMeta]) -> OwnershipEntity:
    nodes = [chain[-1] for chain in chains]
    distinct = _distinct_chains(chains)
    carried = [share for chain in distinct if (share := _carried(chain)) is not None]
    strongest = max(distinct, key=lambda chain: (_carried(chain) or 0.0, -len(chain)))
    direct = next((chain[0] for chain in distinct if len(chain) == 1), None)
    return OwnershipEntity(
        pid=pid,
        name=node_name(meta.get(pid)),
        entity_type=nodes[0].type,
        effective_share_percent=sum(carried) if carried else None,
        share_unknown_on_some_chain=len(carried) < len(distinct),
        direct_share_percent=(direct.share_percent or None) if direct is not None else None,
        depth=min(len(chain) for chain in distinct),
        chains=len(distinct),
        roles=unique(node.role for node in nodes),
        end_of_chain=not any(node.children for node in nodes),
        flags=unique(flag for node in nodes for flag in node.flags or []),
        alerts=unique(
            alert for node in nodes for alert in node.alerts or [] if not is_hidden_alert(alert)
        ),
        strongest_chain=[
            ChainLink(
                pid=node.id or "",
                name=node_name(meta.get(node.id or "")),
                share_percent=node.share_percent or None,
            )
            for node in strongest
        ],
    )


def _distinct_chains(chains: list[_Chain]) -> list[_Chain]:
    """One chain per sequence of pids, the one carrying the largest share. Polixis may list an
    entity twice under one parent, such as once per role, and those nodes are one holding:
    summing both would count its share twice.
    """
    strongest: dict[tuple[str, ...], _Chain] = {}
    for chain in chains:
        # Nodes without an id cannot be told apart, so each keeps its own chain.
        pids = tuple(node.id or f"anonymous:{id(node)}" for node in chain)
        kept = strongest.get(pids)
        if kept is None or (_carried(chain) or 0.0) > (_carried(kept) or 0.0):
            strongest[pids] = chain
    return list(strongest.values())


def _carried(chain: _Chain) -> float | None:
    """The share carried through every link of the chain, or None when a link has none."""
    carried = 100.0
    for node in chain:
        if not node.share_percent:
            return None
        carried *= node.share_percent / 100
    return carried
