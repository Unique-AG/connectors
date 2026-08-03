from collections.abc import Sequence
from dataclasses import dataclass

from fastmcp import Context

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.party_resolver.disambiguate import disambiguate_party
from backstop_mcp.party_resolver.email import looks_like_email
from backstop_mcp.party_resolver.search import quick_search, search_by_email
from backstop_mcp.party_resolver.types import (
    BatchNeedsDisambiguation,
    BatchPartyResolveResult,
    BatchResolved,
    NotFound,
    PartyCandidate,
    PartyResolveItem,
    PartyResolveResult,
    QuickSearchOptions,
    Resolved,
    ResolvedItem,
    ResolvedParty,
    SearchType,
    UnresolvedPartyItem,
)


@dataclass(frozen=True)
class _Ambiguous:
    candidates: tuple[PartyCandidate, ...]
    search: str
    search_type: SearchType


type _ResolveOneResult = Resolved | NotFound | _Ambiguous


def _normalize_party_id_or_search(
    party_id: str | None,
    search: str | None,
) -> tuple[str | None, str | None]:
    normalized_party_id = (party_id or "").strip() or None
    normalized_search = (search or "").strip() or None
    if (normalized_party_id is None) == (normalized_search is None):
        raise ValueError("Exactly one of party_id or search must be provided")
    return normalized_party_id, normalized_search


async def _resolve_one(
    client: BackstopClient,
    *,
    search_type: SearchType,
    party_id: str | None = None,
    search: str | None = None,
    name: str | None = None,
    quick_search_options: QuickSearchOptions | None = None,
) -> _ResolveOneResult:
    assert (party_id is None) != (search is None), (
        "Exactly one of party_id or search must be provided"
    )

    if party_id is not None:
        return Resolved(party=ResolvedParty(id=party_id, type=search_type, name=name))

    assert search is not None
    if looks_like_email(search):
        candidates = await search_by_email(client, search_type=search_type, email=search)
    else:
        candidates = await quick_search(
            client,
            search_type=search_type,
            search=search,
            options=quick_search_options,
        )

    if len(candidates) == 0:
        return NotFound(search=search, search_type=search_type)
    if len(candidates) == 1:
        candidate = candidates[0]
        return Resolved(
            party=ResolvedParty(id=candidate.id, type=search_type, name=candidate.name),
        )
    return _Ambiguous(candidates=candidates, search=search, search_type=search_type)


async def resolve_party(
    ctx: Context,
    client: BackstopClient,
    *,
    search_type: SearchType,
    party_id: str | None = None,
    search: str | None = None,
    name: str | None = None,
    quick_search_options: QuickSearchOptions | None = None,
) -> PartyResolveResult:
    party_id, search = _normalize_party_id_or_search(party_id, search)
    outcome = await _resolve_one(
        client,
        search_type=search_type,
        party_id=party_id,
        search=search,
        name=name,
        quick_search_options=quick_search_options,
    )
    if isinstance(outcome, _Ambiguous):
        return await disambiguate_party(
            ctx,
            candidates=outcome.candidates,
            search=outcome.search,
            search_type=outcome.search_type,
        )
    return outcome


async def resolve_parties(
    ctx: Context,
    client: BackstopClient,
    *,
    search_type: SearchType,
    items: Sequence[PartyResolveItem],
    quick_search_options: QuickSearchOptions | None = None,
) -> BatchPartyResolveResult:
    _ = ctx
    resolved: list[ResolvedItem] = []
    unresolved: list[UnresolvedPartyItem] = []

    for index, item in enumerate(items):
        outcome = await _resolve_one(
            client,
            search_type=search_type,
            party_id=item.party_id,
            search=item.search,
            name=item.name,
            quick_search_options=quick_search_options,
        )
        if isinstance(outcome, Resolved):
            resolved.append(ResolvedItem(item_index=index, party=outcome.party))
        elif isinstance(outcome, NotFound):
            unresolved.append(
                UnresolvedPartyItem(
                    item_index=index,
                    search=outcome.search,
                    search_type=outcome.search_type,
                    candidates=(),
                )
            )
        else:
            unresolved.append(
                UnresolvedPartyItem(
                    item_index=index,
                    search=outcome.search,
                    search_type=outcome.search_type,
                    candidates=outcome.candidates,
                )
            )

    if unresolved:
        return BatchNeedsDisambiguation(
            unresolved=tuple(unresolved),
            resolved=tuple(resolved),
        )
    return BatchResolved(parties=tuple(item.party for item in resolved))
