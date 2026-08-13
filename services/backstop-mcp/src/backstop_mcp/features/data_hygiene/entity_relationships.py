"""Pull `entityRelationships` (+ nested types) out of a by-id JSON:API document.

Relationships are followed from the primary resource's linkage; types are selected by resource
type because a nested include leaves nothing on the primary pointing at them. Callers unpack the
result into `EmploymentIndexFactory.index`.
"""

import logging
from typing import TypedDict

from pydantic import ValidationError

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopApiResourceDocument,
    follow_included,
    included_by_type,
)
from backstop_mcp.features.data_hygiene.types import (
    EntityRelationshipAttributes,
    EntityRelationshipRef,
    RelationshipTypeAttributes,
)

logger = logging.getLogger(__name__)

type RelationshipResource = BackstopApiResource[EntityRelationshipAttributes]
type RelationshipTypeResource = BackstopApiResource[RelationshipTypeAttributes]


class EntityRelationships(TypedDict):
    relationships: list[RelationshipResource]
    relationship_types: list[RelationshipTypeResource]


def _parse_resources[AttrT](
    raw_items: list[dict[str, object]],
    *,
    schema: type[AttrT],
    kind: str,
) -> list[BackstopApiResource[AttrT]]:
    parsed: list[BackstopApiResource[AttrT]] = []
    for raw in raw_items:
        try:
            parsed.append(BackstopApiResource[schema].model_validate(raw))
        except ValidationError as exc:
            logger.warning(
                "data_hygiene.side_load.unreadable",
                extra={"kind": kind, "error": str(exc)},
            )
    return parsed


def entity_relationships[AttrT](
    document: BackstopApiResourceDocument[AttrT],
) -> EntityRelationships:
    """`relationships` and `relationship_types` for an employment index, from one document."""
    return {
        "relationships": _parse_resources(
            follow_included(document, document.data, EntityRelationshipRef.RELATIONSHIPS),
            schema=EntityRelationshipAttributes,
            kind="entityRelationships",
        ),
        "relationship_types": _parse_resources(
            included_by_type(document, EntityRelationshipRef.TYPES_RESOURCE),
            schema=RelationshipTypeAttributes,
            kind="entity-relationship-types",
        ),
    }
