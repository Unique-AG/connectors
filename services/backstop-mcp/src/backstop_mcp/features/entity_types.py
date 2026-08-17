"""Shared Backstop entity-type vocabulary (party search and employment classification).

One singular-alias table, one normalizer, one known-type list. Party search is a closed subset
(`SearchType`). The custom-field catalog uses a separate enum (`CustomFieldEntityType` in
`features/custom_fields/entity_types.py`), not this module.
"""

import re
from enum import StrEnum
from typing import Final, Literal, cast


class EntityType(StrEnum):
    """Canonical plural API resource names this connector knows about."""

    ORGANIZATIONS = "organizations"
    CONTACTS = "contacts"
    PEOPLE = "people"
    EMPLOYEES = "employees"
    OPPORTUNITIES = "opportunities"
    ACCOUNTS = "accounts"


# Party-searchable resource types. Closed because `/quick-search` and the email-field map only
# make sense for these four.
type SearchType = Literal["organizations", "contacts", "people", "employees"]

PARTY_SEARCH_TYPES: Final[frozenset[EntityType]] = frozenset(
    {
        EntityType.ORGANIZATIONS,
        EntityType.CONTACTS,
        EntityType.PEOPLE,
        EntityType.EMPLOYEES,
    }
)

# Party tools and employment accept CRM singulars ("organization") as well as API path-segment
# plurals ("organizations"). Plural forms are accepted via `EntityType(...)`.
_SINGULAR_ALIASES: dict[str, EntityType] = {
    "organization": EntityType.ORGANIZATIONS,
    "contact": EntityType.CONTACTS,
    "person": EntityType.PEOPLE,
    "employee": EntityType.EMPLOYEES,
    "opportunity": EntityType.OPPORTUNITIES,
    "account": EntityType.ACCOUNTS,
}

# The entity types this connector names — derived from the enum rather than restated, so
# adding a member can't leave the two lists disagreeing.
KNOWN_ENTITY_TYPES: tuple[EntityType, ...] = tuple(EntityType)

_COLLAPSE_RE = re.compile(r"[\s_-]+")


def normalize_entity_type(entity_type: str) -> EntityType | None:
    """Normalize a CRM `entityType` or API path segment to a known `EntityType`, if any."""
    collapsed = _COLLAPSE_RE.sub("", entity_type.strip().lower())
    aliased = _SINGULAR_ALIASES.get(collapsed)
    if aliased is not None:
        return aliased
    try:
        return EntityType(collapsed)
    except ValueError:
        return None


def party_search_type(entity_type: str) -> SearchType | None:
    """Return the canonical party `SearchType` when `entity_type` normalizes to one.

    Prefer this over a `TypeGuard` on the raw input: singular CRM forms like `organization`
    normalize successfully but are not themselves `SearchType` literals.
    """
    normalized = normalize_entity_type(entity_type)
    if normalized is None or normalized not in PARTY_SEARCH_TYPES:
        return None
    return cast(SearchType, normalized.value)


def is_party_search_type(entity_type: str) -> bool:
    """Whether `entity_type` normalizes to a party-searchable resource type."""
    return party_search_type(entity_type) is not None
