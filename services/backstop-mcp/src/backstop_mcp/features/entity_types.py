"""Canonical Backstop entity-type vocabulary shared by party and custom-field resolution.

One alias table, one normalizer, one known-type list. Party search is a closed subset
(`SearchType`); custom-field tools accept free-form strings that go through
`normalize_entity_type` so CRM singulars (`organization`) land on the same plural keys the
schema index and party tools use.
"""

from enum import StrEnum
from typing import Final, Literal, TypeGuard


class EntityType(StrEnum):
    """Canonical plural API resource names this connector knows about."""

    ORGANIZATIONS = "organizations"
    CONTACTS = "contacts"
    PEOPLE = "people"
    EMPLOYEES = "employees"
    OPPORTUNITIES = "opportunities"
    ACCOUNTS = "accounts"


# Party-searchable resource types. Closed because `/quick-search` and the email-field map only
# make sense for these four; custom-field glossaries also cover opportunities/accounts.
type SearchType = Literal["organizations", "contacts", "people", "employees"]

PARTY_SEARCH_TYPES: Final[tuple[SearchType, ...]] = (
    "organizations",
    "contacts",
    "people",
    "employees",
)

# Backstop's `custom-field-definitions.entityType` is singular ("organization") while the API
# path segment is plural ("organizations"). Anything not listed passes through lowercased —
# better to index an unrecognized entity type under its own name than to drop its fields.
_ALIASES: dict[str, EntityType] = {
    "organization": EntityType.ORGANIZATIONS,
    "organizations": EntityType.ORGANIZATIONS,
    "contact": EntityType.CONTACTS,
    "contacts": EntityType.CONTACTS,
    "person": EntityType.PEOPLE,
    "people": EntityType.PEOPLE,
    "employee": EntityType.EMPLOYEES,
    "employees": EntityType.EMPLOYEES,
    "opportunity": EntityType.OPPORTUNITIES,
    "opportunities": EntityType.OPPORTUNITIES,
    "account": EntityType.ACCOUNTS,
    "accounts": EntityType.ACCOUNTS,
}

# The entity types this connector surfaces glossaries and tools for — derived from the enum
# rather than restated, so adding a member can't leave the two lists disagreeing.
KNOWN_ENTITY_TYPES: tuple[EntityType, ...] = tuple(EntityType)

assert set(PARTY_SEARCH_TYPES) <= {member.value for member in EntityType}, (
    "every SearchType must be a KNOWN_ENTITY_TYPES member"
)


def normalize_entity_type(entity_type: str) -> str:
    """Normalize a CRM `entityType` or API path segment to the canonical plural form."""
    collapsed = entity_type.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    known = _ALIASES.get(collapsed)
    return known.value if known is not None else entity_type.strip().lower()


def is_party_search_type(entity_type: str) -> TypeGuard[SearchType]:
    """Whether `entity_type` normalizes to a party-searchable resource type."""
    return normalize_entity_type(entity_type) in PARTY_SEARCH_TYPES
