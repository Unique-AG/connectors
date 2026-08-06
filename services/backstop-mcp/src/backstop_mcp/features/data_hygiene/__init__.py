"""Read-response provenance and departed-contact detection.

The public surface is deliberately small: `EmploymentIndexFactory.index_for_person` /
`index_for_organization` for the employment index, `entity_relationships` to pull the
side-loads those methods take, and `extract_as_of` for provenance. `employment.py` is the pure
scan the factory composes — importable for tests, not part of what tools are handed.
"""

from backstop_mcp.features.data_hygiene.employment import (
    EmploymentIndex,
    build_organization_employment_index,
    build_person_employment_index,
)
from backstop_mcp.features.data_hygiene.entity_relationships import entity_relationships
from backstop_mcp.features.data_hygiene.provenance import extract_as_of
from backstop_mcp.features.data_hygiene.responses import (
    AsOfEcho,
    DepartedContactEcho,
    as_of_echo,
    departed_echo,
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
    TypeVocabulary,
)

__all__ = [
    "AsOf",
    "AsOfEcho",
    "DepartedContactEcho",
    "DepartedEmployment",
    "DepartureSignal",
    "EmploymentIndex",
    "EmploymentIndexFactory",
    "EmploymentRules",
    "EmploymentStatus",
    "EntityRelationshipInclude",
    "EntityRelationshipRef",
    "TypeVocabulary",
    "as_of_echo",
    "build_organization_employment_index",
    "build_person_employment_index",
    "create_employment_index_factory",
    "departed_echo",
    "entity_relationships",
    "extract_as_of",
]
