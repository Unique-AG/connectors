import logging

from with_intelligence_mcp.features.consultants.api_responses import ConsultantExtendedAttributes
from with_intelligence_mcp.features.consultants.resolve_consultant import resolve_consultant
from with_intelligence_mcp.features.consultants.responses import (
    ConsultantAmbiguousResponse,
    ConsultantNotEntitledResponse,
    ConsultantNotFoundResponse,
    ConsultantProfileResponse,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

logger = logging.getLogger(__name__)

type GetConsultantResult = (
    ConsultantProfileResponse
    | ConsultantAmbiguousResponse
    | ConsultantNotEntitledResponse
    | ConsultantNotFoundResponse
)


class GetConsultantQuery:
    def __init__(self, *, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(self, *, name: str | None, consultant_id: int | None) -> GetConsultantResult:
        record = await resolve_consultant(self._client, name, consultant_id)
        if not isinstance(record, ConsultantExtendedAttributes):
            logger.info("consultant.resolve.unresolved", extra={"status": record.status})
            return record
        response = ConsultantProfileResponse.from_attributes(record)
        logger.info("consultant.fetched", extra={"consultant_id": response.id})
        return response
