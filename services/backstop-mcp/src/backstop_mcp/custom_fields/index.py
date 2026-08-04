from __future__ import annotations

import re

from backstop_mcp.custom_fields.overrides import normalize_entity_type
from backstop_mcp.custom_fields.types import (
    CustomFieldDefinition,
    FieldAmbiguous,
    FieldCandidate,
    FieldNotFound,
    FieldResolved,
    FieldResolveResult,
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_query(value: str) -> str:
    return _NON_ALNUM.sub(" ", value.strip().lower()).strip()


def build_index(
    definitions: list[CustomFieldDefinition],
) -> dict[str, list[CustomFieldDefinition]]:
    """Group definitions by normalized entity type."""
    index: dict[str, list[CustomFieldDefinition]] = {}
    for definition in definitions:
        key = normalize_entity_type(definition.entity_type)
        index.setdefault(key, []).append(definition)
    return index


def _exact_names(definition: CustomFieldDefinition) -> set[str]:
    names = {definition.crm_name, definition.display_name, *definition.aliases}
    return {normalize_query(n) for n in names if n and normalize_query(n)}


def resolve_in_index(
    index: dict[str, list[CustomFieldDefinition]],
    *,
    entity_type: str,
    query: str,
) -> FieldResolveResult:
    entity = normalize_entity_type(entity_type)
    needle = normalize_query(query)
    if not needle:
        return FieldNotFound(query=query, entity_type=entity)

    definitions = index.get(entity, [])
    exact = [d for d in definitions if needle in _exact_names(d)]
    if len(exact) == 1:
        return FieldResolved(definition=exact[0])
    if len(exact) > 1:
        return FieldAmbiguous(
            query=query,
            entity_type=entity,
            candidates=tuple(_candidate(d) for d in exact),
        )

    fuzzy = [
        d for d in definitions if any(needle in name or name in needle for name in _exact_names(d))
    ]
    if len(fuzzy) == 1:
        return FieldResolved(definition=fuzzy[0])
    if len(fuzzy) > 1:
        return FieldAmbiguous(
            query=query,
            entity_type=entity,
            candidates=tuple(_candidate(d) for d in fuzzy),
        )

    return FieldNotFound(query=query, entity_type=entity)


def _candidate(definition: CustomFieldDefinition) -> FieldCandidate:
    label = definition.display_name
    if definition.crm_name and definition.crm_name != definition.display_name:
        label = f"{definition.display_name} (crm: {definition.crm_name})"
    return FieldCandidate(
        definition_id=definition.definition_id,
        display_name=definition.display_name,
        crm_name=definition.crm_name,
        entity_type=definition.entity_type,
        label=label,
    )
