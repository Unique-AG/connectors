"""Read-response provenance and departed-contact detection.

The public surface is deliberately small: `EmploymentIndexFactory.index` for the employment
index (person or organization side-loads), `EmploymentIndex.links` for the tool-facing list,
`entity_relationships` to pull those includes, and `extract_as_of` for provenance.
`employment.py` is the pure scan the factory composes — importable for tests, not part of what
tools are handed.
"""

from backstop_mcp.features.data_hygiene.employment import EmploymentIndex, build_employment_index
from backstop_mcp.features.data_hygiene.entity_relationships import entity_relationships
from backstop_mcp.features.data_hygiene.provenance import extract_as_of
from backstop_mcp.features.data_hygiene.responses import (
    DepartedContactResponse,
    EmploymentLinkResponse,
    as_of_response,
    departed_response,
)
from backstop_mcp.features.data_hygiene.service import (
    EmploymentIndexFactory,
    create_employment_index_factory,
)
from backstop_mcp.features.data_hygiene.types import (
    AsOf,
    DepartedEmployment,
    DepartureSignal,
    EmploymentRules,
    EmploymentStatus,
    EntityRelationshipInclude,
    EntityRelationshipRef,
    ProvenanceFields,
    TypeVocabulary,
)

__all__ = [
    "AsOf",
    "DepartedContactResponse",
    "DepartedEmployment",
    "DepartureSignal",
    "EmploymentIndex",
    "EmploymentIndexFactory",
    "EmploymentLinkResponse",
    "EmploymentRules",
    "EmploymentStatus",
    "EntityRelationshipInclude",
    "EntityRelationshipRef",
    "ProvenanceFields",
    "TypeVocabulary",
    "as_of_response",
    "build_employment_index",
    "create_employment_index_factory",
    "departed_response",
    "entity_relationships",
    "extract_as_of",
]
