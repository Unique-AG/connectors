from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from with_intelligence_mcp.with_intelligence_client import NotEntitled


class _Listed(Protocol):
    id: int
    name: str | None
    updated_at: str | None


async def resolve_by_name_or_id[RecordT, AmbiguousT, NotFoundT, NotEntitledT](
    *,
    name: str | None,
    record_id: int | None,
    kind: str,
    search: Callable[[str], Awaitable[tuple[Sequence[_Listed], int]]],
    fetch: Callable[[int], Awaitable[RecordT | None]],
    not_found: Callable[..., NotFoundT],
    not_entitled: Callable[..., NotEntitledT],
    ambiguous: Callable[..., AmbiguousT],
    candidate: Callable[..., object],
) -> RecordT | AmbiguousT | NotFoundT | NotEntitledT:
    resolved_id = record_id
    if resolved_id is None:
        if name is None:
            return not_found(searched_for="", hint=f"Pass either name or {kind}_id.")
        try:
            matches, total = await search(name)
        except NotEntitled as error:
            return not_entitled(
                searched_for=name,
                hint=(
                    f"With Intelligence refused the {kind} search for this account "
                    f"({error.path}) — the data is outside its licensed packages."
                ),
            )
        if not matches:
            return not_found(
                searched_for=name,
                hint=(
                    f"No {kind} name contains that text. Matching is partial, so a shorter or "
                    "differently spelled fragment may find it."
                ),
            )
        if len(matches) > 1:
            return ambiguous(
                searched_for=name,
                candidates=[
                    candidate(id=match.id, name=match.name, updated_at=match.updated_at)
                    for match in matches
                ],
                total_matches=total,
            )
        resolved_id = matches[0].id

    try:
        record = await fetch(resolved_id)
    except NotEntitled as error:
        return not_entitled(
            searched_for=name or str(resolved_id),
            hint=(
                f"With Intelligence refused {error.path} for this account — "
                "the data is outside its licensed packages."
            ),
        )
    if record is None:
        return not_found(
            searched_for=name or str(resolved_id),
            hint=f"No {kind} with id {resolved_id}.",
        )
    return record
