"""Normalization of Backstop `entityType` strings to API path segments.

Lives on its own (rather than inside `overrides.py`, which is about a different concern) because
everything in this package keys on the normalized form: the schema index, the glossary scopes,
the override keys, and the value-read paths.
"""

# Backstop's `custom-field-definitions.entityType` is singular ("organization") while the API
# path segment is plural ("organizations"). Anything not listed passes through lowercased —
# better to index an unrecognized entity type under its own name than to drop its fields.
_ALIASES: dict[str, str] = {
    "organization": "organizations",
    "organizations": "organizations",
    "contact": "contacts",
    "contacts": "contacts",
    "person": "people",
    "people": "people",
    "employee": "employees",
    "employees": "employees",
    "opportunity": "opportunities",
    "opportunities": "opportunities",
    "account": "accounts",
    "accounts": "accounts",
}

# The entity types this connector surfaces glossaries and tools for — derived from the alias
# table rather than restated, so adding an alias can't leave the two lists disagreeing.
KNOWN_ENTITY_TYPES: tuple[str, ...] = tuple(dict.fromkeys(_ALIASES.values()))


def normalize_entity_type(entity_type: str) -> str:
    """Normalize a CRM `entityType` or API path segment to the canonical plural form."""
    collapsed = entity_type.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return _ALIASES.get(collapsed, entity_type.strip().lower())
