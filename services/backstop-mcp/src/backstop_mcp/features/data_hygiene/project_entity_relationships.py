"""Pull `entityRelationships` (+ nested types) out of a by-id JSON:API document.

Relationships are followed from the primary resource's linkage; types are selected by resource
type because a nested include leaves nothing on the primary pointing at them. Callers pass the
result into `EmploymentIndexFactory.index`.
"""

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopApiResourceDocument,
    filter_included,
    follow_included,
)
from backstop_mcp.features.data_hygiene.api_responses import (
    EntityRelationshipAttributes,
    EntityRelationshipRef,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.data_hygiene.internal_dto import EntityRelationshipsDto


def project_entity_relationships[AttrT](
    document: BackstopApiResourceDocument[AttrT],
) -> EntityRelationshipsDto:
    """`relationships` and `relationship_types` for an employment index, from one document."""
    return EntityRelationshipsDto(
        relationships=filter_included(
            follow_included(document.included, document.data, EntityRelationshipRef.RELATIONSHIPS),
            schema=BackstopApiResource[EntityRelationshipAttributes],
        ),
        relationship_types=filter_included(
            document.included,
            resource_type=EntityRelationshipRef.TYPES_RESOURCE,
            schema=BackstopApiResource[RelationshipTypeAttributes],
        ),
    )
