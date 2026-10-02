"""Managers: resolving one by name, and the record behind it."""

from with_intelligence_mcp.features.managers.api_responses import (
    ManagerExtendedAttributes,
    ManagerListItemAttributes,
)
from with_intelligence_mcp.features.managers.dependencies import get_manager_query_factory
from with_intelligence_mcp.features.managers.queries import GetManagerQuery
from with_intelligence_mcp.features.managers.responses import (
    ManagerAmbiguousResponse,
    ManagerNotEntitledResponse,
    ManagerNotFoundResponse,
    ManagerProfileResponse,
)

__all__ = [
    "GetManagerQuery",
    "ManagerAmbiguousResponse",
    "ManagerExtendedAttributes",
    "ManagerListItemAttributes",
    "ManagerNotEntitledResponse",
    "ManagerNotFoundResponse",
    "ManagerProfileResponse",
    "get_manager_query_factory",
]
