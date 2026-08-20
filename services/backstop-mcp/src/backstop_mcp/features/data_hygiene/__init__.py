"""Read-response provenance and departed-contact detection.

The public surface is deliberately small: `EmploymentIndexFactory.index` for the employment
index (person or organization side-loads), `EmploymentLinkResponse` for the tool-facing list,
`entity_relationships` to pull those includes, and `AsOfResponse.from_attributes` for provenance.
`employment.py` is the pure scan the factory composes — importable for tests, not part of what
tools are handed.
"""

from backstop_mcp.features.data_hygiene.api_responses import (
    EntityRefAttributes,
    EntityRelationshipAttributes,
    EntityRelationshipInclude,
    EntityRelationshipRef,
    ProvenanceAttributes,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.data_hygiene.employment import EmploymentIndex, build_employment_index
from backstop_mcp.features.data_hygiene.entity_relationships import entity_relationships
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
from backstop_mcp.features.data_hygiene.responses import (
    AsOfResponse,
    DepartedContactResponse,
    EmploymentLinkResponse,
)
from backstop_mcp.features.data_hygiene.service import EmploymentIndexFactory

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
    "build_employment_index",
    "entity_relationships",
]
