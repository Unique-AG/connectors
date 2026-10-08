import logging

from pydantic import TypeAdapter

from with_intelligence_mcp.features.consultants.api_responses import (
    ConsultantExtendedAttributes,
    ConsultantListItemAttributes,
)
from with_intelligence_mcp.features.consultants.responses import (
    ConsultantAmbiguousResponse,
    ConsultantCandidateResponse,
    ConsultantNotEntitledResponse,
    ConsultantNotFoundResponse,
    ConsultantProfileResponse,
)
from with_intelligence_mcp.utils.resolve import resolve_by_name_or_id
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    Page,
    QueryValue,
    WithIntelligenceClient,
)

logger = logging.getLogger(__name__)
_CONSULTANT_RESPONSE = TypeAdapter(ConsultantExtendedAttributes)
_CONSULTANTS_PAGE = TypeAdapter(Page[ConsultantListItemAttributes])

type GetConsultantResult = (
    ConsultantProfileResponse
    | ConsultantAmbiguousResponse
    | ConsultantNotEntitledResponse
    | ConsultantNotFoundResponse
)
type _ConsultantResolution = (
    ConsultantExtendedAttributes
    | ConsultantAmbiguousResponse
    | ConsultantNotEntitledResponse
    | ConsultantNotFoundResponse
)


class GetConsultantQuery:
    def __init__(self, *, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(self, *, name: str | None, consultant_id: int | None) -> GetConsultantResult:
        record = await self._resolve(name=name, consultant_id=consultant_id)
        if not isinstance(record, ConsultantExtendedAttributes):
            logger.info("consultant.resolve.unresolved", extra={"status": record.status})
            return record
        response = ConsultantProfileResponse.from_attributes(record)
        logger.info("consultant.fetched", extra={"consultant_id": response.id})
        return response

    async def _resolve(
        self, *, name: str | None, consultant_id: int | None
    ) -> _ConsultantResolution:
        return await resolve_by_name_or_id(
            name=name,
            record_id=consultant_id,
            kind="consultant",
            search=self._search_by_name,
            fetch=self._fetch,
            not_found=ConsultantNotFoundResponse,
            not_entitled=ConsultantNotEntitledResponse,
            ambiguous=ConsultantAmbiguousResponse,
            candidate=ConsultantCandidateResponse,
        )

    async def _search_by_name(self, name: str) -> tuple[list[ConsultantListItemAttributes], int]:
        params: dict[str, QueryValue] = {"name": [name]}
        if self._client.asset_class_groups:
            params["asset_class_group"] = list(self._client.asset_class_groups)
        page = await self._client.get_page(
            "/v3/consultants", _CONSULTANTS_PAGE, params, page=1, page_size=10
        )
        return page.results, page.pagination.total

    async def _fetch(self, consultant_id: int) -> ConsultantExtendedAttributes | None:
        try:
            return await self._client.get_json(
                f"/v3/consultants/{consultant_id}", _CONSULTANT_RESPONSE
            )
        except NotFound:
            return None
