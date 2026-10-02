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
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
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
        resolved_id = manager_id
        if resolved_id is None:
            if name is None:
                return ManagerNotFoundResponse(
                    searched_for="", hint="Pass either name or manager_id."
                )
            try:
                matches, total = await self._search_by_name(name)
            except NotEntitled as error:
                return ManagerNotEntitledResponse(
                    searched_for=name,
                    hint=(
                        "With Intelligence refused the manager search for this account "
                        f"({error.path}) — the data is outside its licensed packages."
                    ),
                )
            if not matches:
                return ManagerNotFoundResponse(
                    searched_for=name,
                    hint=(
                        "No manager name contains that text. Matching is partial, so a shorter or "
                        "differently spelled fragment may find it."
                    ),
                )
            if len(matches) > 1:
                return ManagerAmbiguousResponse(
                    searched_for=name,
                    candidates=[
                        ManagerCandidateResponse(
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
            return ManagerNotEntitledResponse(
                searched_for=name or str(resolved_id),
                hint=(
                    f"With Intelligence refused {error.path} for this account — "
                    "the data is outside its licensed packages."
                ),
            )
        if record is None:
            return ManagerNotFoundResponse(
                searched_for=name or str(resolved_id),
                hint=f"No manager with id {resolved_id}.",
            )
        return record

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
