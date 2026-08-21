from collections.abc import Mapping

from pydantic import validate_email
from pydantic_core import PydanticCustomError

from backstop_mcp.backstop_client import (
    BackstopApiCollectionDocument,
    BackstopApiResource,
)
from backstop_mcp.features.entity_types import SearchType, party_search_type
from backstop_mcp.features.party_resolver.api_responses import PartyAttributes
from backstop_mcp.features.party_resolver.internal_dto import PartyCandidate, ResolvedPartyDto
from backstop_mcp.features.resolution import Candidate

# Plain assignments (not `type` statements) — `schema=` needs a real class object, and a PEP 695
# type alias isn't assignable to `type[T]` even though it resolves to one at runtime.
PartyCollectionDocument = BackstopApiCollectionDocument[PartyAttributes]
_PartyResource = BackstopApiResource[PartyAttributes]

EMAIL_FIELDS: Mapping[SearchType, tuple[str, ...]] = {
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
BACKSTOP_SEARCH_TYPES: Mapping[SearchType, str] = {
    "organizations": "ORGANIZATION",
    "contacts": "PERSON_FIRST_NAME,PERSON_LAST_NAME",
    "people": "PERSON_FIRST_NAME,PERSON_LAST_NAME",
    "employees": "PERSON_FIRST_NAME,PERSON_LAST_NAME",
}

# Singular kind shown on candidate labels (elicitation enum and ambiguous payload). The
# structured `search_type` stays the API plural; the label is what a person reads.
SEARCH_TYPE_LABEL: Mapping[SearchType, str] = {
    "organizations": "organization",
    "contacts": "contact",
    "people": "person",
    "employees": "employee",
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


def candidates_from_document(
    document: PartyCollectionDocument, *, search_type: SearchType
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
    party_id = _party_id(resource)
    # Backstop ids are not unique across collections. Namespace the elicit key by
    # search_type so `enhance_search_types` hits that share an id stay distinct options.
    return Candidate(
        key=f"{resolved_search_type}:{party_id}",
        label=_candidate_label(name=name, search_type=resolved_search_type, party_id=party_id),
        value=ResolvedPartyDto(id=party_id, search_type=resolved_search_type, name=name),
    )


def _candidate_label(*, name: str | None, search_type: SearchType, party_id: str) -> str:
    """Name plus entity kind, so elicitation and the ambiguous payload say what the hit is.

    `search_type` on the candidate is still the API plural (`people`); the parenthetical is
    the readable singular (`person`) so two 'Jane's of different kinds are distinguishable
    without reading a sibling field.
    """
    kind = SEARCH_TYPE_LABEL[search_type]
    if name is not None:
        return f"{name} ({kind})"
    return f"{kind} #{party_id}"
