"""Tool meta helpers for custom-field glossary scopes on MCP tools."""

from typing import Final, cast

from backstop_mcp.features.entity_types import EntityType

# MCP tool `meta` key listing which entity types get a custom-field glossary on tools/list.
GLOSSARY_ENTITIES_META_KEY: Final = "backstop.glossary_entities"


def glossary_meta(*entity_types: EntityType) -> dict[str, list[str]]:
    """Build tool meta declaring glossary scopes as canonical entity-type strings."""
    return {GLOSSARY_ENTITIES_META_KEY: [entity.value for entity in entity_types]}


def parse_glossary_entities(meta: dict[str, object] | None) -> tuple[EntityType, ...]:
    """Read `GLOSSARY_ENTITIES_META_KEY` from tool meta; ignore unknown / malformed values."""
    if not meta:
        return ()
    raw = meta.get(GLOSSARY_ENTITIES_META_KEY)
    if not isinstance(raw, list):
        return ()
    entities: list[EntityType] = []
    for item in cast(list[object], raw):
        if not isinstance(item, str):
            continue
        try:
            entities.append(EntityType(item))
        except ValueError:
            continue
    return tuple(entities)
