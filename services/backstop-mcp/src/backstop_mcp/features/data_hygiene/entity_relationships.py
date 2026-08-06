"""Pull `entityRelationships` (+ nested types) out of a by-id JSON:API document.

Relationships are followed from the primary resource's linkage; types are selected by resource
type because a nested include leaves nothing on the primary pointing at them. Callers unpack the
result into `EmploymentIndexFactory.index_for_person` / `index_for_organization`.
"""

from typing import TypedDict

from backstop_mcp.backstop_client import (
    BackstopApiResourceDocument,
    follow_included,
    included_by_type,
)
from backstop_mcp.features.data_hygiene.types import EntityRelationshipRef


class EntityRelationships(TypedDict):
    relationships: list[dict[str, object]]
    relationship_types: list[dict[str, object]]


def entity_relationships[AttrT](
    document: BackstopApiResourceDocument[AttrT],
) -> EntityRelationships:
    """`relationships` and `relationship_types` for an employment index, from one document."""
    return {
        "relationships": follow_included(
            document, document.data, EntityRelationshipRef.RELATIONSHIPS
        ),
        "relationship_types": included_by_type(document, EntityRelationshipRef.TYPES_RESOURCE),
    }
