import logging

from pydantic import TypeAdapter

from with_intelligence_mcp.features.managers.api_responses import (
    ManagerExtendedAttributes,
    ManagerListItemAttributes,
)
from with_intelligence_mcp.features.managers.responses import (
    ManagerAmbiguousResponse,
    ManagerCandidateResponse,
    ManagerNotEntitledResponse,
    ManagerNotFoundResponse,
    ManagerProfileResponse,
)
from with_intelligence_mcp.utils.resolve import resolve_by_name_or_id
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    Page,
    QueryValue,
    WithIntelligenceClient,
)

logger = logging.getLogger(__name__)
_MANAGER_RESPONSE = TypeAdapter(ManagerExtendedAttributes)
_MANAGERS_PAGE = TypeAdapter(Page[ManagerListItemAttributes])

type GetManagerResult = (
    ManagerProfileResponse
    | ManagerAmbiguousResponse
    | ManagerNotEntitledResponse
    | ManagerNotFoundResponse
)
type _ManagerResolution = (
    ManagerExtendedAttributes
    | ManagerAmbiguousResponse
    | ManagerNotEntitledResponse
    | ManagerNotFoundResponse
)


class GetManagerQuery:
    def __init__(self, *, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(self, *, name: str | None, manager_id: int | None) -> GetManagerResult:
        record = await self._resolve(name=name, manager_id=manager_id)
        if not isinstance(record, ManagerExtendedAttributes):
            logger.info("manager.resolve.unresolved", extra={"status": record.status})
            return record
        response = ManagerProfileResponse.from_attributes(record)
        logger.info("manager.fetched", extra={"manager_id": response.id})
        return response

    async def _resolve(self, *, name: str | None, manager_id: int | None) -> _ManagerResolution:
        return await resolve_by_name_or_id(
            name=name,
            record_id=manager_id,
            kind="manager",
            search=self._search_by_name,
            fetch=self._fetch,
            not_found=ManagerNotFoundResponse,
            not_entitled=ManagerNotEntitledResponse,
            ambiguous=ManagerAmbiguousResponse,
            candidate=ManagerCandidateResponse,
        )

    async def _search_by_name(self, name: str) -> tuple[list[ManagerListItemAttributes], int]:
        params: dict[str, QueryValue] = {"name": [name]}
        if self._client.asset_class_groups:
            params["asset_class_group"] = list(self._client.asset_class_groups)
        page = await self._client.get_page(
            "/v3/managers", _MANAGERS_PAGE, params, page=1, page_size=10
        )
        return page.results, page.pagination.total

    async def _fetch(self, manager_id: int) -> ManagerExtendedAttributes | None:
        try:
            return await self._client.get_json(f"/v3/managers/{manager_id}", _MANAGER_RESPONSE)
        except NotFound:
            return None
