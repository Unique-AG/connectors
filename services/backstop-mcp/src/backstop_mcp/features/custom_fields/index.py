import re

from backstop_mcp.features.custom_fields.entity_types import normalize_entity_type
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.features.resolution import Candidate, NotFound, Resolution, from_candidates

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

type DefinitionIndex = dict[str, list[CustomFieldDefinition]]

# Custom-field resolution is one instance of the shared algebra in `resolution.py`: same result
# types, same ambiguity policy, same status strings as party resolution.
type FieldCandidate = Candidate[CustomFieldDefinition]
type FieldResolution = Resolution[CustomFieldDefinition]


def normalize_query(value: str) -> str:
    return _NON_ALNUM.sub(" ", value.strip().lower()).strip()


def build_index(definitions: list[CustomFieldDefinition]) -> DefinitionIndex:
    """Group definitions by normalized entity type."""
    index: DefinitionIndex = {}
    for definition in definitions:
        key = normalize_entity_type(definition.entity_type)
        index.setdefault(key, []).append(definition)
    return index


def _searchable_names(definition: CustomFieldDefinition) -> set[str]:
    names = {definition.crm_name, definition.display_name, *definition.aliases}
    return {normalize_query(n) for n in names if n and normalize_query(n)}


def candidate_for(definition: CustomFieldDefinition) -> FieldCandidate:
    label = definition.display_name
    if definition.crm_name and definition.crm_name != definition.display_name:
        label = f"{definition.display_name} (crm: {definition.crm_name})"
    return Candidate(key=definition.definition_id, label=label, value=definition)


def resolve_in_index(
    index: DefinitionIndex,
    *,
    entity_type: str,
    query: str,
) -> FieldResolution:
    """Resolve a field by human name or alias, exact matches outranking partial ones.

    Two tiers, and the first non-empty one decides: an exact (normalized) name match, then a
    substring match either way. Tiering matters because a user's short phrase ("grade") is a
    substring of several instance field names ("Investor Grade", "Grade Review Date") while
    being an exact match for at most one — without the tiers, the exact hit would be drowned
    in its own near-misses and every lookup would prompt.
    """
    entity = normalize_entity_type(entity_type)
    needle = normalize_query(query)
    if not needle:
        return NotFound(query=query, scope=entity)

    definitions = index.get(entity, [])

    exact = [d for d in definitions if needle in _searchable_names(d)]
    if exact:
        return from_candidates([candidate_for(d) for d in exact], query=query, scope=entity)

    partial = [
        d
        for d in definitions
        if any(needle in name or name in needle for name in _searchable_names(d))
    ]
    return from_candidates([candidate_for(d) for d in partial], query=query, scope=entity)
