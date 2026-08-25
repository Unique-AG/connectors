import asyncio
from collections.abc import Sequence

from fastmcp import Context

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver._party_search_types import normalized_email
from backstop_mcp.features.party_resolver.fetch_party_name import fetch_party_name
from backstop_mcp.features.party_resolver.internal_dto import (
    BatchPartyResolution,
    PartyResolution,
    PartyResolveItemDto,
    QuickSearchOptionsDto,
    ResolvedPartyDto,
)
from backstop_mcp.features.party_resolver.quick_search import quick_search
from backstop_mcp.features.party_resolver.search_by_email import search_by_email
from backstop_mcp.features.party_resolver.search_by_like import search_by_like
from backstop_mcp.features.resolution import (
    Ambiguous,
    Resolved,
    collect_batch,
    elicit_choice,
    from_candidates,
)


async def _resolve_one(
    client: BackstopClient,
    *,
    search_type: SearchType,
    item: PartyResolveItemDto,
    confirm_name: bool = False,
    quick_search_options: QuickSearchOptionsDto | None = None,
) -> PartyResolution:
    if item.party_id is not None:
        resolved_name = item.name
        if resolved_name is None and confirm_name:
            resolved_name = await fetch_party_name(
                client, search_type=search_type, party_id=item.party_id
            )
        return Resolved(
            value=ResolvedPartyDto(id=item.party_id, search_type=search_type, name=resolved_name)
        )

    assert item.search is not None
    email = normalized_email(item.search)
    if email is not None:
        candidates = await search_by_email(client, search_type=search_type, email=email)
    else:
        candidates = await quick_search(
            client,
            search_type=search_type,
            search=item.search,
            options=quick_search_options,
        )
        if not candidates:
            candidates = await search_by_like(client, search_type=search_type, search=item.search)

    return from_candidates(candidates, query=item.search, scope=search_type)


async def resolve_party(
    ctx: Context,
    client: BackstopClient,
    *,
    search_type: SearchType,
    party_id: str | None = None,
    search: str | None = None,
    name: str | None = None,
    confirm_name: bool = False,
    quick_search_options: QuickSearchOptionsDto | None = None,
) -> PartyResolution:
    """Resolve one party from a name, an email, or a trusted Party ID.

    Set `confirm_name` when the caller has no other way to learn the party's name — it costs
    one extra `fields=name` request on the trusted-`party_id` path, and buys the echo that
    makes a wrong id visible instead of silent. Callers that fetch the record anyway (e.g.
    `get_organization`) leave it off and backfill from their own response.
    """
    item = PartyResolveItemDto(party_id=party_id, search=search, name=name)
    outcome = await _resolve_one(
        client,
        search_type=search_type,
        item=item,
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
    items: Sequence[PartyResolveItemDto],
    confirm_name: bool = False,
    quick_search_options: QuickSearchOptionsDto | None = None,
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
                item=item,
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
