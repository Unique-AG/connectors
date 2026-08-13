import asyncio
from collections.abc import Mapping, Sequence
from urllib.parse import quote

from pydantic import validate_email
from pydantic_core import PydanticCustomError

from backstop_mcp.backstop_client import (
    BackstopApiCollectionDocument,
    BackstopApiResource,
    BackstopApiResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.entity_types import party_search_type
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

# Backstop's `/quick-search` rejects our lowercase `SearchType` outright (400
# InvalidParameterException: valid options are [ALL, ACCOUNT, ..., ORGANIZATION,
# PERSON_FIRST_NAME, PERSON_LAST_NAME, ..., EMAIL_ADDRESS, ...]) — these are the mapped values.
# A name query might land in either the first- or last-name field, so people/contacts/employees
# search both; `filter[searchTypes][eq]` takes a comma-joined multi-value the same way
# `activityType` does elsewhere in this API.
_BACKSTOP_SEARCH_TYPES: Mapping[SearchType, str] = {
    "organizations": "ORGANIZATION",
    "contacts": "PERSON_FIRST_NAME,PERSON_LAST_NAME",
    "people": "PERSON_FIRST_NAME,PERSON_LAST_NAME",
    "employees": "PERSON_FIRST_NAME,PERSON_LAST_NAME",
}


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
    fields = _EMAIL_FIELDS[search_type]
    documents = await asyncio.gather(
        *(
            client.get(
                f"/{search_type}",
                params={f"filter[{field}][eq]": email},
                schema=_PartyCollectionDocument,
            )
            for field in fields
        )
    )
    return _merge_candidates(documents, search_type=search_type)


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
    params: dict[str, object] = {
        "filter[searchText][eq]": search,
        "filter[searchTypes][eq]": _backstop_search_types(search_type=search_type, search=search),
        "filter[limit][eq]": options.limit,
        "filter[showAll][eq]": options.show_all,
        "filter[enhanceSearchTypes][eq]": options.enhance_search_types,
        "page[limit]": options.limit,
        "page[offset]": 0,
    }

    if options.full_email_match is None:
        if looks_like_email(search):
            params["filter[fullEmailMatch][eq]"] = True
    else:
        params["filter[fullEmailMatch][eq]"] = options.full_email_match

    if options.filter_type is not None:
        params["filter[filterType][eq]"] = options.filter_type

    return params


def _backstop_search_types(*, search_type: SearchType, search: str) -> str:
    """Map `search_type` to Backstop's uppercase `searchTypes` enum value(s).

    When `search` itself looks like an email, `EMAIL_ADDRESS` is added to the person-shaped
    mapping so a quick-search direct caller (unlike `resolve.py`'s `_resolve_one`, which routes
    email-looking input to `search_by_email` instead) still matches on it.
    """
    base = _BACKSTOP_SEARCH_TYPES[search_type]
    if search_type != "organizations" and looks_like_email(search):
        return f"{base},EMAIL_ADDRESS"
    return base


def _merge_candidates(
    documents: Sequence[_PartyCollectionDocument], *, search_type: SearchType
) -> tuple[PartyCandidate, ...]:
    by_id: dict[str, PartyCandidate] = {}
    for document in documents:
        for candidate in _candidates_from_document(document, search_type=search_type):
            by_id.setdefault(candidate.key, candidate)
    return tuple(by_id.values())


def _candidates_from_document(
    document: _PartyCollectionDocument, *, search_type: SearchType
) -> tuple[PartyCandidate, ...]:
    return tuple(
        _candidate_from_resource(resource, search_type=search_type) for resource in document.data
    )


def _party_id(resource: _PartyResource) -> str:
    """Extract the id usable in a follow-up `GET /{search_type}/{id}`.

    Quick-search hits come back with a prefixed `id` (`organizations_341208613`), which
    `NumberFormatException`s against the live API when interpolated as-is. `attributes.resourceId`
    carries the real id when present; other party endpoints don't send that attribute, so fall
    back to stripping the `{type}_` prefix off `id` (only when it's actually there).
    """
    if resource.attributes.resource_id is not None:
        return resource.attributes.resource_id
    prefix = f"{resource.type}_"
    if resource.id.startswith(prefix):
        return resource.id.removeprefix(prefix)
    return resource.id


def _candidate_from_resource(
    resource: _PartyResource, *, search_type: SearchType
) -> PartyCandidate:
    # `resource.id` is already stripped and guaranteed non-blank by `BackstopApiResource`'s
    # schema validation; a blank `type` still falls back to "resource" here since that's a
    # caller-side display concern, not a structural defect the schema should reject.
    #
    # Prefer the resource's own type when `enhance_search_types` returns a different party
    # kind — stamping the requested scope would send a later trusted-id fetch to the wrong
    # collection. Fall back to the requested scope only when the wire type isn't a party
    # SearchType (shouldn't happen for `/quick-search` hits, but keep a usable candidate).
    resource_type = resource.type or "resource"
    resolved_search_type = party_search_type(resource_type) or search_type
    name = resource.attributes.display_name()
    label = name if name is not None else f"{resource_type} #{resource.id}"
    # `Candidate.key` stays `resource.id`: it's only a UI selection key for the elicitation
    # flow, and the wire id is a fine, unique key even prefixed. `ResolvedParty.id` is what
    # later gets interpolated into a Backstop path, so it needs the real, unprefixed id.
    return Candidate(
        key=resource.id,
        label=label,
        value=ResolvedParty(id=_party_id(resource), search_type=resolved_search_type, name=name),
    )
