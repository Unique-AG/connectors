"""Consultants: resolving one firm by name, and the record behind it."""

from with_intelligence_mcp.features.consultants.api_responses import (
    ConsultantExtendedAttributes,
    ConsultantListItemAttributes,
)
from with_intelligence_mcp.features.consultants.dependencies import get_consultant_query_factory
from with_intelligence_mcp.features.consultants.queries import GetConsultantQuery
from with_intelligence_mcp.features.consultants.responses import (
    ConsultantAmbiguousResponse,
    ConsultantNotEntitledResponse,
    ConsultantNotFoundResponse,
    ConsultantProfileResponse,
)

__all__ = [
    "ConsultantAmbiguousResponse",
    "ConsultantExtendedAttributes",
    "ConsultantListItemAttributes",
    "ConsultantNotEntitledResponse",
    "ConsultantNotFoundResponse",
    "ConsultantProfileResponse",
    "GetConsultantQuery",
    "get_consultant_query_factory",
]
