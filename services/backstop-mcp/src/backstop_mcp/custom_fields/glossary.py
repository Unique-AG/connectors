from __future__ import annotations

from backstop_mcp.custom_fields.types import CustomFieldDefinition

# Keep tool descriptions usable for MCP clients / context windows.
DEFAULT_GLOSSARY_BUDGET_CHARS = 6_000


def format_glossary(
    definitions: list[CustomFieldDefinition],
    *,
    entity_type: str,
    budget_chars: int = DEFAULT_GLOSSARY_BUDGET_CHARS,
) -> str:
    """Compact glossary block for one entity type, truncated to `budget_chars`."""
    if not definitions:
        return (
            f"\n\nCustom field glossary ({entity_type}): (none cached yet — "
            + "call resolve_custom_field with refresh=true after connecting.)"
        )

    header = f"\n\nCustom field glossary ({entity_type}):"
    lines = [header]
    used = len(header)
    truncated = False

    for definition in sorted(definitions, key=lambda d: d.display_name.lower()):
        allowed = "|".join(v.label for v in definition.allowed_values[:12])
        if len(definition.allowed_values) > 12:
            allowed += "|…"
        aliases = ", ".join(definition.aliases) if definition.aliases else "—"
        line = (
            f"\n- {definition.display_name} "
            + f"(id={definition.definition_id}, type={definition.field_type or '—'}, "
            + f"timeSeries={'yes' if definition.is_time_series else 'no'}) "
            + f"— aliases: {aliases}"
            + (f"; allowed: {allowed}" if allowed else "")
        )
        if used + len(line) > budget_chars:
            truncated = True
            break
        lines.append(line)
        used += len(line)

    if truncated:
        lines.append(
            "\n- … glossary truncated; call resolve_custom_field to look up further fields."
        )

    return "".join(lines)
