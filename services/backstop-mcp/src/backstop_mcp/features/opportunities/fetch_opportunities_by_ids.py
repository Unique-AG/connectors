"""By-id opportunity fan-out: one GET per id, one catalog load, per-id outcomes."""

import asyncio
import logging
from collections.abc import Mapping, Sequence
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
from backstop_mcp.features.custom_fields import (
    CustomFieldFilters,
    CustomFieldsService,
    RegularCustomFieldValuesAttributes,
)
from backstop_mcp.features.opportunities.fetch_opportunities import (
    OpportunityResource,
    current_stage_id,
    resolve_stage_name,
    stage_history,
    stage_names_from_included,
)
from backstop_mcp.features.opportunities.internal_dto import OpportunityStageDto
from backstop_mcp.features.opportunities.opportunity_stages_service import OpportunityStagesService
from backstop_mcp.features.opportunities.responses import (
    GetOpportunitiesByIdsResponse,
    OpportunityIdErrorResponse,
    OpportunityResponse,
)

logger = logging.getLogger(__name__)

MAX_OPPORTUNITY_IDS = 50
_STAGE_INCLUDE = "stage"
_STAGE_HISTORY_INCLUDE = "stage,stageHistory"

_OpportunityDocument = BackstopApiResourceDocument[dict[str, object]]


@dataclass(frozen=True)
class _FetchedOne:
    opportunity_id: str
    resource: OpportunityResource | None = None
    included: tuple[dict[str, object], ...] = ()
    error: str | None = None
    not_found: bool = False


async def _fetch_one_oportunity(
    client: BackstopClient, *, opportunity_id: str, include: str
) -> _FetchedOne:
    path = f"/opportunities/{quote(opportunity_id, safe='')}"
    try:
        document = await client.get(path, schema=_OpportunityDocument, params={"include": include})
        return _FetchedOne(
            opportunity_id=opportunity_id,
            resource=document.require_data(path=path),
            included=tuple(document.included),
        )
    except BackstopApiError as exc:
        if exc.status_code == HTTPStatus.NOT_FOUND:
            return _FetchedOne(opportunity_id=opportunity_id, not_found=True)
        return _FetchedOne(opportunity_id=opportunity_id, error=exc.detail)
    except BackstopResponseSchemaError:
        return _FetchedOne(opportunity_id=opportunity_id, error="unreadable opportunity document")
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


async def _project_one(
    resource: OpportunityResource,
    *,
    client: BackstopClient,
    resource_included_relations: Sequence[dict[str, object]],
    opportunity_id_to_stage_map: Mapping[str, OpportunityStageDto],
    custom_fields_service: CustomFieldsService,
    custom_field_filters: CustomFieldFilters,
    include_stage_history: bool,
) -> OpportunityResponse | None:
    side_loaded = stage_names_from_included(resource_included_relations)
    try:
        stage_id = current_stage_id(resource)
        custom_field_values = await custom_fields_service.join_values(
            client,
            RegularCustomFieldValuesAttributes.model_validate(
                resource.attributes
            ).regular_custom_field_values,
            filters=custom_field_filters,
        )

        return OpportunityResponse.from_resource(
            resource,
            stage=resolve_stage_name(
                stage_id,
                opportunity_id_to_name_map=side_loaded,
                opportunity_id_to_stage_map=opportunity_id_to_stage_map,
            ),
            stage_id=stage_id,
            stage_history=(
                stage_history(
                    resource,
                    included=resource_included_relations,
                    opportunity_id_to_name_map=side_loaded,
                    opportunity_stages=opportunity_id_to_stage_map,
                )
                if include_stage_history
                else ()
            ),
            custom_field_values=tuple(custom_field_values),
        )
    except ValidationError as exc:
        logger.warning(
            "opportunities.by_ids.record.unreadable",
            extra={"opportunity_id": resource.id},
            exc_info=exc,
        )
        return None


async def fetch_opportunities_by_ids(
    client: BackstopClient,
    *,
    opportunity_ids: Sequence[str],
    include_stage_history: bool,
    opportunity_stages_service: OpportunityStagesService,
    custom_fields_service: CustomFieldsService,
    custom_fields_filters: CustomFieldFilters,
) -> GetOpportunitiesByIdsResponse:
    """GET each id through the client gate; join custom fields from one catalog load."""
    assert len(opportunity_ids) <= MAX_OPPORTUNITY_IDS, (
        f"at most {MAX_OPPORTUNITY_IDS} opportunity ids per call, "
        f"which the tool's own `max_length` already rejects"
    )
    include_query_param = _STAGE_HISTORY_INCLUDE if include_stage_history else _STAGE_INCLUDE
    catalog, opportunity_id_to_stage_map, settled = await asyncio.gather(
        custom_fields_service.load_catalog(client),
        opportunity_stages_service.get(client),
        asyncio.gather(
            *(
                _fetch_one_oportunity(client, opportunity_id=oid, include=include_query_param)
                for oid in opportunity_ids
            ),
            return_exceptions=True,
        ),
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
        assert item.resource is not None
        projected = await _project_one(
            item.resource,
            resource_included_relations=item.included,
            opportunity_id_to_stage_map=opportunity_id_to_stage_map,
            custom_field_filters=custom_fields_filters,
            include_stage_history=include_stage_history,
            client=client,
            custom_fields_service=custom_fields_service,
        )
        if projected is None:
            errors.append(
                OpportunityIdErrorResponse(
                    id=item.opportunity_id, detail="unreadable opportunity record"
                )
            )
            continue
        opportunities.append(projected)
    return GetOpportunitiesByIdsResponse(
        opportunities=tuple(opportunities),
        not_found=tuple(not_found),
        errors=tuple(errors),
        custom_fields_unavailable=catalog is None,
    )
