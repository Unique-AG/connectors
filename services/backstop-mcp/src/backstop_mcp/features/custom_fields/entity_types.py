"""Re-exports of the shared entity-type vocabulary for custom-field call sites.

Canonical definitions live in `features.entity_types` so party resolution and custom fields
share one scope vocabulary.
"""

from backstop_mcp.features.entity_types import KNOWN_ENTITY_TYPES, EntityType, normalize_entity_type

__all__ = ["EntityType", "KNOWN_ENTITY_TYPES", "normalize_entity_type"]
