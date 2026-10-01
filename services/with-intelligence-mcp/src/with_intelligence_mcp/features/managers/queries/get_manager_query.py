import logging

from with_intelligence_mcp.features.managers.api_responses import ManagerExtendedAttributes
from with_intelligence_mcp.features.managers.resolve_manager import resolve_manager
from with_intelligence_mcp.features.managers.responses import (
    ManagerAmbiguousResponse,
    ManagerNotEntitledResponse,
    ManagerNotFoundResponse,
    ManagerProfileResponse,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

logger = logging.getLogger(__name__)

type GetManagerResult = (
    ManagerProfileResponse
    | ManagerAmbiguousResponse
    | ManagerNotEntitledResponse
    | ManagerNotFoundResponse
)


class GetManagerQuery:
    def __init__(self, *, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(self, *, name: str | None, manager_id: int | None) -> GetManagerResult:
        record = await resolve_manager(self._client, name, manager_id)
        if not isinstance(record, ManagerExtendedAttributes):
            logger.info("manager.resolve.unresolved", extra={"status": record.status})
            return record
        response = ManagerProfileResponse.from_attributes(record)
        logger.info("manager.fetched", extra={"manager_id": response.id})
        return response
