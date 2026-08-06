import asyncio
from collections.abc import Mapping, Sequence
from urllib.parse import quote

from backstop_mcp.backstop_client import (
    BackstopApiCollectionDocument,
    BackstopApiResource,
    BackstopApiResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.party_resolver.email import looks_like_email
from backstop_mcp.features.party_resolver.types import (
    PartyAttributes,
    PartyCandidate,
    QuickSearchOptions,
    ResolvedParty,
    SearchType,
)
from backstop_mcp.features.resolution import Candidate

# Plain assignments (not `type` statements) — `schema=` needs a real class object, and a PEP 695
# type alias isn't assignable to `type[T]` even though it resolves to one at runtime.
_PartyCollectionDocument = BackstopApiCollectionDocument[PartyAttributes]
_PartyResourceDocument = BackstopApiResourceDocument[PartyAttributes]
_PartyResource = BackstopApiResource[PartyAttributes]

_EMAIL_FIELDS: Mapping[SearchType, tuple[str, ...]] = {
    "organizations": ("email",),
    "contacts": ("email",),
    "people": ("email", "email2", "email3"),
    "employees": ("email", "email2", "email3"),
}


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

    The fan-out is safe to gather: concurrency is gated per upstream request inside
    `BackstopClient`, not per client, so these queue against the per-user limit rather than
    breaching it.
    """
    fields = _EMAIL_FIELDS[search_type]
    responses = await asyncio.gather(
        *(
            client.get(
                f"/{search_type}",
                params={f"filter[{field}][eq]": email},
                schema=_PartyCollectionDocument,
            )
            for field in fields
        )
    )
    return _merge_candidates(responses, search_type=search_type)


async def quick_search(
    client: BackstopClient,
    *,
    search_type: SearchType,
    search: str,
    options: QuickSearchOptions | None = None,
) -> tuple[PartyCandidate, ...]:
    """Fuzzy/name lookup via `GET /quick-search`, pinned to a single `search_type`.

    The only fuzzy primitive Backstop offers: its filter operators are `eq, neq, gt, ge, lt, le`,
    so `filter[name][eq]=Capstone` returns nothing when the stored record is
    "Capstone Investment Advisors LP".
    """
    resolved_options = options if options is not None else QuickSearchOptions()
    response = await client.get(
        "/quick-search",
        params=_quick_search_params(
            search_type=search_type,
            search=search,
            options=resolved_options,
        ),
        schema=_PartyCollectionDocument,
    )
    return _candidates_from_document(response, search_type=search_type)


async def fetch_party_name(
    client: BackstopClient, *, search_type: SearchType, party_id: str
) -> str | None:
    """Look up just the display name for a known party id.

    Used to honour "every successful resolution echoes the resolved name + Party ID" on the
    trusted-`party_id` path, where no search ran and so no name was ever seen.
    """
    document = await client.get(
        f"/{search_type}/{quote(party_id, safe='')}",
        params={"fields": "name,firstName,lastName"},
        schema=_PartyResourceDocument,
    )
    return document.data.attributes.display_name()


def _quick_search_params(
    *,
    search_type: SearchType,
    search: str,
    options: QuickSearchOptions,
) -> dict[str, object]:
    assert options.limit > 0, "QuickSearchOptions.limit must be positive"

    params: dict[str, object] = {
        "filter[searchText][eq]": search,
        "filter[searchTypes][eq]": search_type,
        "filter[limit][eq]": options.limit,
        "filter[showAll][eq]": _bool_param(options.show_all),
        "filter[enhanceSearchTypes][eq]": _bool_param(options.enhance_search_types),
        "page[limit]": options.limit,
        "page[offset]": 0,
    }

    if options.full_email_match is None:
        if looks_like_email(search):
            params["filter[fullEmailMatch][eq]"] = "true"
    else:
        params["filter[fullEmailMatch][eq]"] = _bool_param(options.full_email_match)

    if options.filter_type is not None:
        params["filter[filterType][eq]"] = options.filter_type

    return params


def _bool_param(value: bool) -> str:
    return "true" if value else "false"


def _merge_candidates(
    documents: Sequence[_PartyCollectionDocument], *, search_type: SearchType
) -> tuple[PartyCandidate, ...]:
    seen_ids: set[str] = set()
    merged: list[PartyCandidate] = []
    for document in documents:
        for candidate in _candidates_from_document(document, search_type=search_type):
            if candidate.key in seen_ids:
                continue
            seen_ids.add(candidate.key)
            merged.append(candidate)
    return tuple(merged)


def _candidates_from_document(
    document: _PartyCollectionDocument, *, search_type: SearchType
) -> tuple[PartyCandidate, ...]:
    return tuple(
        _candidate_from_resource(resource, search_type=search_type) for resource in document.data
    )


def _candidate_from_resource(
    resource: _PartyResource, *, search_type: SearchType
) -> PartyCandidate:
    # `resource.id` is already stripped and guaranteed non-blank by `BackstopApiResource`'s
    # schema validation; a blank `type` still falls back to "resource" here since that's a
    # caller-side display concern, not a structural defect the schema should reject.
    resource_type = resource.type or "resource"
    name = resource.attributes.display_name()
    label = name if name is not None else f"{resource_type} #{resource.id}"
    return Candidate(
        key=resource.id,
        label=label,
        value=ResolvedParty(id=resource.id, type=search_type, name=name),
    )