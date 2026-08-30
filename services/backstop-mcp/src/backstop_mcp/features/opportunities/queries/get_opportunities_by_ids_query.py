import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopApiResourceDocument,
    BackstopClient,
    BackstopResponseSchemaError,
)
from backstop_mcp.features.custom_fields import CustomFieldFilters
from backstop_mcp.features.opportunities.api_responses import OpportunityResourceAttributes
from backstop_mcp.features.opportunities.resource_utils.map_opportunity_to_response_util import (
    MapOpportunityToResponseUtil,
)
from backstop_mcp.features.opportunities.responses import (
    GetOpportunitiesByIdsResponse,
    OpportunityIdErrorResponse,
    OpportunityResponse,
)

logger = logging.getLogger(__name__)

MAX_OPPORTUNITY_IDS = 50


@dataclass(frozen=True)
class _FetchedOne:
    opportunity_id: str
    opportunity_response: OpportunityResponse | None = None
    included: tuple[dict[str, object], ...] = ()
    error: str | None = None
    not_found: bool = False


class GetOpportunitiesByIdsQuery:
    def __init__(
        self,
        *,
        client: BackstopClient,
        map_opportunity_to_response_util: MapOpportunityToResponseUtil,
    ) -> None:
        self._client: BackstopClient = client
        self._map_opportunity_to_response_util: MapOpportunityToResponseUtil = (
            map_opportunity_to_response_util
        )

    async def run(
        self,
        *,
        opportunity_ids: Sequence[str],
        include_stage_history: bool,
        custom_fields_filters: CustomFieldFilters,
    ) -> GetOpportunitiesByIdsResponse:
        """GET each id through the client gate; join custom fields from one catalog load."""
        assert len(opportunity_ids) <= MAX_OPPORTUNITY_IDS, (
            f"at most {MAX_OPPORTUNITY_IDS} opportunity ids per call, "
            f"which the tool's own `max_length` already rejects"
        )
        include_relations = ["stage"]
        if include_stage_history:
            include_relations.append("stageHistory")
        include_query_param = ",".join(include_relations)

        settled = await asyncio.gather(
            *(
                self._fetch_one_opportunity(
                    opportunity_id=opportunity_id,
                    include_query_param=include_query_param,
                    custom_fields_filters=custom_fields_filters,
                    include_stage_history=include_stage_history,
                )
                for opportunity_id in opportunity_ids
            ),
            return_exceptions=True,
        )
        # `_get_one` reports a 404, a Backstop error status, an unreadable body and a transport
        # failure against its own id, so what reaches here is a revoked credential, cancellation, or
        # a bug — none of which the other ids survive either. Gathered with `return_exceptions` so
        # every request settles before one of them raises.
        fetched: list[_FetchedOne] = []
        for result in settled:
            if isinstance(result, BaseException):
                raise result
            fetched.append(result)

        opportunities: list[OpportunityResponse] = []
        not_found: list[str] = []
        errors: list[OpportunityIdErrorResponse] = []
        for item in fetched:
            if item.not_found:
                not_found.append(item.opportunity_id)
                continue
            if item.error is not None:
                errors.append(OpportunityIdErrorResponse(id=item.opportunity_id, detail=item.error))
                continue
            assert item.opportunity_response is not None
            opportunities.append(item.opportunity_response)
        return GetOpportunitiesByIdsResponse(
            opportunities=tuple(opportunities),
            not_found=tuple(not_found),
            errors=tuple(errors),
        )

    async def _fetch_one_opportunity(
        self,
        *,
        opportunity_id: str,
        include_query_param: str,
        custom_fields_filters: CustomFieldFilters,
        include_stage_history: bool,
    ) -> _FetchedOne:
        path = f"/opportunities/{quote(opportunity_id, safe='')}"
        try:
            document = await self._client.get(
                path,
                schema=BackstopApiResourceDocument[OpportunityResourceAttributes],
                params={"include": include_query_param},
            )
            resource_raw = document.require_data(path=path)
            resource = await self._map_opportunity_to_response_util.run(
                row=resource_raw,
                api_include_resources=document.included,
                custom_fields_filters=custom_fields_filters,
                include_stage_history=include_stage_history,
            )
            return _FetchedOne(
                opportunity_id=opportunity_id,
                opportunity_response=resource,
                included=tuple(document.included),
            )
        except BackstopApiError as exc:
            if exc.status_code == HTTPStatus.NOT_FOUND:
                return _FetchedOne(opportunity_id=opportunity_id, not_found=True)
            return _FetchedOne(opportunity_id=opportunity_id, error=exc.detail)
        except BackstopResponseSchemaError:
            return _FetchedOne(
                opportunity_id=opportunity_id, error="unreadable opportunity document"
            )
        except ValidationError:
            logger.warning(
                "opportunities.by_ids.record.unreadable",
                extra={"opportunity_id": opportunity_id},
                exc_info=True,
            )
            return _FetchedOne(opportunity_id=opportunity_id, error="unreadable opportunity record")
        except httpx.RequestError:
            # Only a 429 classified as `concurrency` is retried, so a timeout on one of 50 ids
            # arrives here. Failing the batch over it would cost the caller the other 49.
            logger.warning(
                "opportunities.by_ids.request_failed",
                extra={"opportunity_id": opportunity_id},
                exc_info=True,
            )
            return _FetchedOne(
                opportunity_id=opportunity_id, error="Backstop did not answer for this id"
            )
