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
        if key is None:
            continue
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


def _partial_score(query: str, name: str) -> int | None:
    """Rank a substring hit; higher is better. `None` means no match.

    Prefer starts-with over query-in-name over name-in-query. Reverse containment requires a
    query of at least two characters so a one-letter field name cannot match every query.
    Within a tier, shorter names win (subtract length).
    """
    if name.startswith(query):
        return 300 - len(name)
    if query in name:
        return 200 - len(name)
    if len(query) >= 2 and name in query:
        return 100 - len(name)
    return None


def _best_partial_score(query: str, definition: CustomFieldDefinition) -> int | None:
    best: int | None = None
    for name in _searchable_names(definition):
        score = _partial_score(query, name)
        if score is None:
            continue
        if best is None or score > best:
            best = score
    return best


def resolve_in_index(
    index: DefinitionIndex,
    *,
    entity_type: str,
    query: str,
) -> FieldResolution:
    """Resolve a field by human name or alias, exact matches outranking partial ones.

    Two tiers, and the first non-empty one decides: an exact (normalized) name match, then a
    scored substring match. Scoring matters because a user's short phrase ("grade") is a
    substring of several instance field names ("Investor Grade", "Grade Review Date") while
    being a clear best match for at most one — without ranking, every near-miss prompts.
    """
    entity = normalize_entity_type(entity_type)
    if entity is None:
        return NotFound(query=query, scope=entity_type)

    normalized_query = normalize_query(query)
    if not normalized_query:
        return NotFound(query=query, scope=entity)

    definitions = index.get(entity, [])

    exact = [d for d in definitions if normalized_query in _searchable_names(d)]
    if exact:
        return from_candidates([candidate_for(d) for d in exact], query=query, scope=entity)

    scored: list[tuple[int, CustomFieldDefinition]] = []
    for definition in definitions:
        score = _best_partial_score(normalized_query, definition)
        if score is not None:
            scored.append((score, definition))
    if not scored:
        return NotFound(query=query, scope=entity)

    best_score = max(score for score, _ in scored)
    winners = [definition for score, definition in scored if score == best_score]
    return from_candidates([candidate_for(d) for d in winners], query=query, scope=entity)
