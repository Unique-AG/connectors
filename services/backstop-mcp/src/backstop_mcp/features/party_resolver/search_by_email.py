import asyncio
from collections.abc import Sequence

from pydantic import validate_email
from pydantic_core import PydanticCustomError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver._party_search_types import (
    EMAIL_FIELDS,
    PartyCollectionDocument,
    candidates_from_document,
)
from backstop_mcp.features.party_resolver.internal_dto import PartyCandidate


def normalized_email(value: str) -> str | None:
    """Return pydantic's normalized address, or `None` when `value` is not an email.

    Accepts display-name forms (`"Bob" <bob@example.com>`) and surrounding whitespace; the
    returned string is what Backstop's exact `email` / `email2` / `email3` filters expect.
    """
    try:
        _name, email = validate_email(value)
    except PydanticCustomError:
        return None
    return email


def looks_like_email(value: str) -> bool:
    """Return True when `value` is a valid email (pydantic / email-validator)."""
    return normalized_email(value) is not None


async def search_by_email(
    client: BackstopClient,
    *,
    search_type: SearchType,
    email: str,
) -> tuple[PartyCandidate, ...]:
    """Exact-match email lookup across the email fields applicable to `search_type`.

    Queries each field separately (never AND-ed) and dedupes hits by resource id. Backstop
    stores up to three addresses per person/employee, so checking only `email` would silently
    miss a match on `email2`/`email3`.

    `email` should already be normalized (see `normalized_email`); this path filters with the
    string as given.

    The fan-out is safe to gather: concurrency is gated per upstream request inside
    `BackstopClient`, not per client, so these queue against the per-user limit rather than
    breaching it.
    """
    fields = EMAIL_FIELDS[search_type]
    documents = await asyncio.gather(
        *(
            client.get(
                f"/{search_type}",
                params={f"filter[{field}][eq]": email},
                schema=PartyCollectionDocument,
            )
            for field in fields
        )
    )
    return _merge_candidates(documents, search_type=search_type)


def _merge_candidates(
    documents: Sequence[PartyCollectionDocument], *, search_type: SearchType
) -> tuple[PartyCandidate, ...]:
    by_id: dict[str, PartyCandidate] = {}
    for document in documents:
        for candidate in candidates_from_document(document, search_type=search_type):
            by_id.setdefault(candidate.key, candidate)
    return tuple(by_id.values())
