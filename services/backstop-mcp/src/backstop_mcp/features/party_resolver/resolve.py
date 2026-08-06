import asyncio
from collections.abc import Sequence

from fastmcp import Context

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.party_resolver.email import looks_like_email
from backstop_mcp.features.party_resolver.search import (
    fetch_party_name,
    quick_search,
    search_by_email,
)
from backstop_mcp.features.party_resolver.types import (
    BatchPartyResolution,
    PartyResolution,
    PartyResolveItem,
    QuickSearchOptions,
    ResolvedParty,
    SearchType,
)
from backstop_mcp.features.resolution import (
    Ambiguous,
    Resolved,
    collect_batch,
    elicit_choice,
    from_candidates,
)


def _normalize_party_id_or_search(
    party_id: str | None,
    search: str | None,
) -> tuple[str | None, str | None]:
    normalized_party_id = (party_id or "").strip() or None
    normalized_search = (search or "").strip() or None
    if (normalized_party_id is None) == (normalized_search is None):
        raise ValueError("Exactly one of party_id or search must be provided")
    # `party_id` is a caller-trusted shortcut that skips any existence check and later gets
    # interpolated into a Backstop request path (e.g. `/organizations/{id}`) — reject a
    # value containing '/' so a crafted party_id can't redirect the request to an
    # unintended path/endpoint.
    if normalized_party_id is not None and "/" in normalized_party_id:
        raise ValueError(f"party_id {normalized_party_id!r} must not contain '/'")
    return normalized_party_id, normalized_search


async def _resolve_one(
    client: BackstopClient,
    *,
    search_type: SearchType,
    party_id: str | None = None,
    search: str | None = None,
    name: str | None = None,
    confirm_name: bool = False,
    quick_search_options: QuickSearchOptions | None = None,
) -> PartyResolution:
    assert (party_id is None) != (search is None), (
        "Exactly one of party_id or search must be provided"
    )

    if party_id is not None:
        resolved_name = name
        if resolved_name is None and confirm_name:
            resolved_name = await fetch_party_name(
                client, search_type=search_type, party_id=party_id
            )
        return Resolved(value=ResolvedParty(id=party_id, type=search_type, name=resolved_name))

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

    return from_candidates(candidates, query=search, scope=search_type)


async def resolve_party(
    ctx: Context,
    client: BackstopClient,
    *,
    search_type: SearchType,
    party_id: str | None = None,
    search: str | None = None,
    name: str | None = None,
    confirm_name: bool = False,
    quick_search_options: QuickSearchOptions | None = None,
) -> PartyResolution:
    """Resolve one party from a name, an email, or a trusted Party ID.

    Set `confirm_name` when the caller has no other way to learn the party's name — it costs
    one extra `fields=name` request on the trusted-`party_id` path, and buys the echo that
    makes a wrong id visible instead of silent. Callers that fetch the record anyway (e.g.
    `get_organization`) leave it off and backfill from their own response.
    """
    party_id, search = _normalize_party_id_or_search(party_id, search)
    outcome = await _resolve_one(
        client,
        search_type=search_type,
        party_id=party_id,
        search=search,
        name=name,
        confirm_name=confirm_name,
        quick_search_options=quick_search_options,
    )
    if isinstance(outcome, Ambiguous):
        return await elicit_choice(
            ctx,
            outcome,
            prompt=(f'Multiple {outcome.scope} matched "{outcome.query}". Which one did you mean?'),
        )
    return outcome


async def resolve_parties(
    client: BackstopClient,
    *,
    search_type: SearchType,
    items: Sequence[PartyResolveItem],
    confirm_name: bool = False,
    quick_search_options: QuickSearchOptions | None = None,
) -> BatchPartyResolution:
    """Resolve several parties, returning one combined payload if anything is unresolved.

    Takes no `Context` and never elicits, by design: prompting per item is the "modal storm"
    the batch path exists to avoid, so the model is given every unresolved item at once and
    asks a single question (policy step 3 in `resolution.py`).

    Items resolve concurrently — the per-user concurrency gate lives around each upstream
    request, so the fan-out queues against Backstop's limit instead of breaching it.
    """
    outcomes = await asyncio.gather(
        *(
            _resolve_one(
                client,
                search_type=search_type,
                party_id=item.party_id,
                search=item.search,
                name=item.name,
                confirm_name=confirm_name,
                quick_search_options=quick_search_options,
            )
            for item in items
        )
    )
    return collect_batch(
        [
            (item.search or item.party_id or "", outcome)
            for item, outcome in zip(items, outcomes, strict=True)
        ]
    )
