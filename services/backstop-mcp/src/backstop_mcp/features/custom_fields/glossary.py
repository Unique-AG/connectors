from collections.abc import Sequence

from backstop_mcp.features.custom_fields.types import CustomFieldDefinition

# Budget for everything appended to *one* tool description, not per entity type — a tool scoped
# to every known entity would otherwise multiply this by six and dominate the context window.
DEFAULT_GLOSSARY_BUDGET_CHARS = 6_000

_TRUNCATION_NOTICE = (
    "\n- … glossary truncated; call resolve_custom_field to look up further fields."
)

_MAX_LISTED_ALLOWED_VALUES = 12


def format_glossary(
    definitions: list[CustomFieldDefinition],
    *,
    entity_type: str,
    budget_chars: int = DEFAULT_GLOSSARY_BUDGET_CHARS,
) -> str:
    """Compact glossary block for one entity type, truncated to `budget_chars`.

    Returns `""` when there's nothing to advertise — no definitions, or no budget left for even
    one of them — so tool descriptions are left untouched rather than carrying a bare header.
    Definitions only ever come from a real Backstop fetch (see `CustomFieldsService`), so "empty"
    means "schema not fetched yet", and a guess assembled from env overrides alone would be worse
    than saying nothing.
    """
    if not definitions:
        return ""

    header = f"\n\nCustom field glossary ({entity_type}):"
    lines: list[str] = []
    used = len(header)
    truncated = False

    for definition in sorted(definitions, key=lambda d: d.display_name.lower()):
        line = _definition_line(definition)
        if used + len(line) > budget_chars:
            truncated = True
            break
        lines.append(line)
        used += len(line)

    if not lines:
        return ""
    return header + "".join(lines) + (_TRUNCATION_NOTICE if truncated else "")


def format_glossaries(
    definitions_by_entity: Sequence[tuple[str, list[CustomFieldDefinition]]],
    *,
    budget_chars: int = DEFAULT_GLOSSARY_BUDGET_CHARS,
) -> str:
    """Glossary blocks for several entity types, sharing one budget across all of them.

    Entities are consumed in the order given and the budget is spent as it goes, so a tool scoped
    to many entity types advertises the first few in full and drops the rest rather than emitting
    one full-budget block per type.
    """
    blocks: list[str] = []
    remaining = budget_chars

    for entity_type, definitions in definitions_by_entity:
        block = format_glossary(definitions, entity_type=entity_type, budget_chars=remaining)
        if not block:
            continue
        blocks.append(block)
        remaining -= len(block)

    return "".join(blocks)


def _definition_line(definition: CustomFieldDefinition) -> str:
    allowed = "|".join(v.label for v in definition.allowed_values[:_MAX_LISTED_ALLOWED_VALUES])
    if len(definition.allowed_values) > _MAX_LISTED_ALLOWED_VALUES:
        allowed += "|…"
    aliases = ", ".join(definition.aliases) if definition.aliases else "—"
    return (
        f"\n- {definition.display_name} "
        + f"(id={definition.definition_id}, type={definition.field_type or '—'}, "
        + f"timeSeries={'yes' if definition.is_time_series else 'no'}) "
        + f"— aliases: {aliases}"
        + (f"; allowed: {allowed}" if allowed else "")
    )
