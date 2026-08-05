"""Read-response provenance and departed-contact detection.

The public surface is deliberately small: `DepartedContactDetector.verify` for the departed
signal and `extract_as_of` for provenance. `departed.py` is the pure scan the detector composes —
importable for tests, not part of what tools are handed.
"""

from backstop_mcp.features.data_hygiene.provenance import extract_as_of
from backstop_mcp.features.data_hygiene.responses import (
    AsOfEcho,
    DepartedContactEcho,
    as_of_echo,
    departed_echo,
)
from backstop_mcp.features.data_hygiene.service import (
    DepartedContactDetector,
    create_departed_contact_detector,
)
from backstop_mcp.features.data_hygiene.types import (
    ENTITY_RELATIONSHIP_TYPES_RESOURCE,
    ENTITY_RELATIONSHIPS_INCLUDE,
    ENTITY_RELATIONSHIPS_RELATIONSHIP,
    AsOf,
    DepartedEmployment,
    DepartureRules,
    DepartureSignal,
    TypeVocabulary,
)

__all__ = [
    "ENTITY_RELATIONSHIPS_INCLUDE",
    "ENTITY_RELATIONSHIPS_RELATIONSHIP",
    "ENTITY_RELATIONSHIP_TYPES_RESOURCE",
    "AsOf",
    "AsOfEcho",
    "DepartedContactDetector",
    "DepartedContactEcho",
    "DepartedEmployment",
    "DepartureRules",
    "DepartureSignal",
    "TypeVocabulary",
    "as_of_echo",
    "create_departed_contact_detector",
    "departed_echo",
    "extract_as_of",
]
