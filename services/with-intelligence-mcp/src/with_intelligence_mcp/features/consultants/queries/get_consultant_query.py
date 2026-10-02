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
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
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
        resolved_id = consultant_id
        if resolved_id is None:
            if name is None:
                return ConsultantNotFoundResponse(
                    searched_for="", hint="Pass either name or consultant_id."
                )
            try:
                matches, total = await self._search_by_name(name)
            except NotEntitled as error:
                return ConsultantNotEntitledResponse(
                    searched_for=name,
                    hint=(
                        "With Intelligence refused the consultant search for this account "
                        f"({error.path}) — the data is outside its licensed packages."
                    ),
                )
            if not matches:
                return ConsultantNotFoundResponse(
                    searched_for=name,
                    hint=(
                        "No consultant name contains that text. Matching is partial, so a shorter "
                        "or differently spelled fragment may find it."
                    ),
                )
            if len(matches) > 1:
                return ConsultantAmbiguousResponse(
                    searched_for=name,
                    candidates=[
                        ConsultantCandidateResponse(
                            id=match.id, name=match.name, updated_at=match.updated_at
                        )
                        for match in matches
                    ],
                    total_matches=total,
                )
            resolved_id = matches[0].id

        try:
            record = await self._fetch(resolved_id)
        except NotEntitled as error:
            return ConsultantNotEntitledResponse(
                searched_for=name or str(resolved_id),
                hint=(
                    f"With Intelligence refused {error.path} for this account — "
                    "the data is outside its licensed packages."
                ),
            )
        if record is None:
            return ConsultantNotFoundResponse(
                searched_for=name or str(resolved_id),
                hint=f"No consultant with id {resolved_id}.",
            )
        return record

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
