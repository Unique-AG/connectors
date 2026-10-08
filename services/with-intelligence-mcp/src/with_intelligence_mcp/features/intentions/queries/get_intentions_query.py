import asyncio
import logging
from typing import Protocol

from pydantic import TypeAdapter

from with_intelligence_mcp.features.intentions.api_responses import (
    IntentionExtendedAttributes,
    IntentionListItemAttributes,
)
from with_intelligence_mcp.features.intentions.responses import (
    IntentionResponse,
    InvestorIntentionsResponse,
)
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
    NotFound,
    Page,
    QueryValue,
    WithIntelligenceClient,
)

logger = logging.getLogger(__name__)
_INTENTION = TypeAdapter(IntentionExtendedAttributes)
_INTENTIONS_PAGE = TypeAdapter(Page[IntentionListItemAttributes])


class _Investor(Protocol):
    id: int
    name: str | None


class GetIntentionsQuery:
    def __init__(self, *, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(
        self,
        *,
        investor: _Investor,
        page: int,
        limit: int,
        updated_since: str | None,
    ) -> InvestorIntentionsResponse:
        listed, total = await self._list_intentions(
            investor_id=investor.id,
            page=page,
            limit=limit,
            updated_since=updated_since,
        )
        details = await asyncio.gather(*(self._fetch_intention(entry.id) for entry in listed))
        refusals = [error for _, error in details if error is not None]
        if listed and len(refusals) == len(listed):
            raise refusals[0]
        intentions = [
            IntentionResponse.from_attributes(record)
            if record is not None
            else IntentionResponse.from_listing(listed[index])
            for index, (record, _) in enumerate(details)
        ]
        response = InvestorIntentionsResponse(
            investor_id=investor.id,
            investor_name=investor.name,
            intentions=intentions,
            total=total,
            returned=len(intentions),
            page=page,
            has_more=(page - 1) * limit + len(intentions) < total,
        )
        logger.info(
            "intentions.investor.fetched",
            extra={"investor_id": investor.id, "returned": response.returned, "total": total},
        )
        return response

    async def _fetch_intention(
        self, intention_id: int
    ) -> tuple[IntentionExtendedAttributes | None, NotEntitled | None]:
        try:
            return await self._client.get_json(f"/v3/intentions/{intention_id}", _INTENTION), None
        except NotFound:
            return None, None
        except NotEntitled as error:
            return None, error

    async def _list_intentions(
        self,
        *,
        investor_id: int,
        page: int,
        limit: int,
        updated_since: str | None,
    ) -> tuple[list[IntentionListItemAttributes], int]:
        params: dict[str, QueryValue] = {
            "investor_id": [investor_id],
            "sort[updated_at]": "desc",
        }
        if self._client.asset_class_groups:
            params["asset_class_group"] = list(self._client.asset_class_groups)
        if updated_since is not None:
            params["updated_at[from]"] = updated_since
        response = await self._client.get_page(
            "/v3/intentions",
            _INTENTIONS_PAGE,
            params,
            page=page,
            page_size=limit,
        )
        return response.results, response.pagination.total
