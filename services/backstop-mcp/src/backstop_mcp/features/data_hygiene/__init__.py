"""Read-response provenance and departed-contact detection.

The public surface is deliberately small: `EmploymentIndexFactory.index` for the employment
index (person or organization side-loads), `EmploymentLinkResponse` for the tool-facing list,
`project_entity_relationships` to pull those includes, and `AsOfResponse.from_attributes` for
provenance.
`employment_index.py` is the winner-per-pair fold the factory composes — importable for tests, not
part of what tools are handed.
"""

from backstop_mcp.features.data_hygiene.api_responses import (
    EntityRefAttributes,
    EntityRelationshipAttributes,
    EntityRelationshipInclude,
    EntityRelationshipRef,
    ProvenanceAttributes,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.data_hygiene.employment_index import EmploymentIndex
from backstop_mcp.features.data_hygiene.employment_index_factory import EmploymentIndexFactory
from backstop_mcp.features.data_hygiene.internal_dto import (
    DepartedEmploymentDto,
    DepartureSignal,
    EmploymentEdgeDto,
    EmploymentRecordDto,
    EmploymentRulesDto,
    EmploymentStatus,
    EntityRelationshipsDto,
    TypeVocabularyDto,
)
from backstop_mcp.features.data_hygiene.project_entity_relationships import (
    project_entity_relationships,
)
from backstop_mcp.features.data_hygiene.responses import (
    AsOfResponse,
    DepartedContactResponse,
    EmploymentLinkResponse,
)

__all__ = [
    "AsOfResponse",
    "DepartedContactResponse",
    "DepartedEmploymentDto",
    "DepartureSignal",
    "EmploymentIndex",
    "EmploymentIndexFactory",
    "EmploymentLinkResponse",
    "EmploymentEdgeDto",
    "EmploymentRecordDto",
    "EmploymentRulesDto",
    "EntityRefAttributes",
    "EmploymentStatus",
    "EntityRelationshipAttributes",
    "EntityRelationshipInclude",
    "EntityRelationshipRef",
    "EntityRelationshipsDto",
    "ProvenanceAttributes",
    "RelationshipTypeAttributes",
    "TypeVocabularyDto",
    "project_entity_relationships",
]
