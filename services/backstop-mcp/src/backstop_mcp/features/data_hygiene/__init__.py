"""Read-response provenance and departed-contact detection.

The public surface is deliberately small: `EmploymentIndexFactory.index` for the employment
index (person or organization side-loads), `EmploymentLinkResponse` for the tool-facing list,
`project_entity_relationships` to pull those includes, and `AsOfResponse.from_attributes` for
provenance.
`EmploymentIndex` is the winner-per-pair fold the factory composes. It is exported because it is
what `EmploymentIndexFactory.index` hands back — a package that publishes a method has to publish
the type on its signature — not so that callers build one. `get_employment_rules` owns the
tenant vocabulary; `EmploymentIndexFactory` consumes it (plus the clock) to build an index.
"""

from backstop_mcp.features.data_hygiene.api_responses import (
    EntityRefAttributes,
    EntityRelationshipAttributes,
    EntityRelationshipInclude,
    EntityRelationshipRef,
    ProvenanceAttributes,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.data_hygiene.dependencies import (
    get_employment_index_factory,
    get_employment_rules,
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
    "get_employment_index_factory",
    "get_employment_rules",
    "project_entity_relationships",
]
