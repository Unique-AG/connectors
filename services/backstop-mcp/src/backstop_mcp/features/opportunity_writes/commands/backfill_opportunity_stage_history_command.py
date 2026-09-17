"""POST `/bulk-opportunity-stage-history`. Appends history rows; does not move a deal's stage."""

import logging
from http import HTTPStatus
from urllib.parse import quote

import httpx
from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopApiSingleResourceDocument,
    BackstopClient,
    BackstopRateLimitError,
    BackstopResponseSchemaError,
    isoformat,
    json_api_create,
    resource_pointer,
)
from backstop_mcp.features.bulk_writes import (
    BulkRequestedRowDto,
    RecordOutcomeResponse,
    bulk_record_outcomes,
)
from backstop_mcp.features.opportunities import (
    OpportunityResourceAttributes,
    OpportunityStagesService,
)
from backstop_mcp.features.opportunity_writes.api_responses import (
    BulkOpportunityStageHistoryAttributes,
    BulkOpportunityStageHistoryDocument,
    BulkOpportunityStageHistoryRecordAttributes,
)
from backstop_mcp.features.opportunity_writes.backfill_opportunity_stage_history_input import (
    BackfillOpportunityStageHistoryInput,
    OpportunityStageHistoryRecordInput,
)
from backstop_mcp.features.opportunity_writes.commands._opportunity_attributes import (
    opportunity_entity_type_id,
)
from backstop_mcp.features.opportunity_writes.responses import (
    BackfillOpportunityStageHistoryResponse,
)

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_OpportunityDocument = BackstopApiSingleResourceDocument[OpportunityResourceAttributes]


class BackfillOpportunityStageHistoryCommand:
    """Append historical stage-history rows. Does not move any deal's current stage."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        opportunity_stages_service: OpportunityStagesService,
    ) -> None:
        self._client: BackstopClient = client
        self._opportunity_stages_service: OpportunityStagesService = opportunity_stages_service

    async def run(
        self, *, backfill: BackfillOpportunityStageHistoryInput
    ) -> BackfillOpportunityStageHistoryResponse:
        with _tracer.start_as_current_span("opportunity_writes.command.backfill_stage_history") as (
            span
        ):
            span.set_attribute("record_count", len(backfill.records))
            entity_type_ids: dict[str, str | None] = {}
            unreadable: dict[str, str] = {}
            for requested_row in backfill.records:
                opportunity_id = requested_row.opportunity_id
                if opportunity_id in entity_type_ids or opportunity_id in unreadable:
                    continue
                entity_type_id, error = await self._entity_type_lookup(opportunity_id)
                if error is not None:
                    unreadable[opportunity_id] = error
                else:
                    entity_type_ids[opportunity_id] = entity_type_id
            posted_indexes: list[int] = []
            posted_rows: list[OpportunityStageHistoryRecordInput] = []
            stage_ids: list[str] = []
            for index, requested_row in enumerate(backfill.records):
                error = unreadable.get(requested_row.opportunity_id)
                if error is not None:
                    continue
                stage = await self._opportunity_stages_service.find_by_stage_name(
                    name=requested_row.stage,
                    entity_type_id=entity_type_ids[requested_row.opportunity_id],
                )
                posted_indexes.append(index)
                posted_rows.append(requested_row)
                stage_ids.append(stage.id)
            if posted_rows:
                payload = json_api_create(
                    resource_type="bulk-opportunity-stage-history",
                    attributes={
                        "records": [
                            {
                                "effectiveDate": isoformat(requested_row.effective_date),
                                "opportunity": resource_pointer(
                                    resource_id=requested_row.opportunity_id,
                                    resource_type="opportunities",
                                ),
                                "stage": resource_pointer(
                                    resource_id=stage_id, resource_type="opportunity-stages"
                                ),
                            }
                            for requested_row, stage_id in zip(posted_rows, stage_ids, strict=True)
                        ]
                    },
                )
                document = await self._client.post(
                    "/bulk-opportunity-stage-history",
                    schema=BulkOpportunityStageHistoryDocument,
                    json=payload,
                )
                posted_outcomes, warnings = self._outcomes(
                    tuple(posted_rows), tuple(stage_ids), document.data.attributes
                )
            else:
                posted_outcomes, warnings = (), ()
            outcomes = self._merge_outcomes(
                record_count=len(backfill.records),
                unreadable=unreadable,
                requested_rows=backfill.records,
                posted_indexes=tuple(posted_indexes),
                posted_outcomes=posted_outcomes,
            )
            applied_count = sum(1 for outcome in outcomes if outcome.status == "applied")
            logger.info(
                "opportunity_writes.stage_history.backfilled",
                extra={
                    "total_count": len(outcomes),
                    "applied_count": applied_count,
                    "failed_count": len(outcomes) - applied_count,
                    "warning_count": len(warnings),
                },
            )
            return BackfillOpportunityStageHistoryResponse(
                total_count=len(outcomes),
                applied_count=applied_count,
                records=outcomes,
                warnings=warnings,
            )

    async def _entity_type_lookup(self, opportunity_id: str) -> tuple[str | None, str | None]:
        try:
            document = await self._client.get(
                f"/opportunities/{quote(opportunity_id, safe='')}",
                schema=_OpportunityDocument,
                params={"include": "clientDefinedEntityType"},
            )
        except BackstopRateLimitError:
            raise
        except BackstopApiError as exc:
            if (
                exc.status_code
                in {
                    HTTPStatus.UNAUTHORIZED,
                    HTTPStatus.FORBIDDEN,
                }
                or exc.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
            ):
                raise
            if exc.status_code == HTTPStatus.NOT_FOUND:
                return None, f"Opportunity {opportunity_id} was not found."
            return None, exc.detail
        except BackstopResponseSchemaError:
            return None, f"Opportunity {opportunity_id} was unreadable."
        except httpx.RequestError:
            logger.warning(
                "opportunity_writes.stage_history.opportunity_lookup_failed",
                extra={"opportunity_id": opportunity_id},
                exc_info=True,
            )
            return None, f"Backstop did not answer for opportunity {opportunity_id}."
        return opportunity_entity_type_id(document), None

    def _merge_outcomes(
        self,
        *,
        record_count: int,
        unreadable: dict[str, str],
        requested_rows: tuple[OpportunityStageHistoryRecordInput, ...],
        posted_indexes: tuple[int, ...],
        posted_outcomes: tuple[RecordOutcomeResponse, ...],
    ) -> tuple[RecordOutcomeResponse, ...]:
        outcomes: dict[int, RecordOutcomeResponse] = {
            index: RecordOutcomeResponse(
                index=index,
                record_id=requested_row.opportunity_id,
                status="failed",
                error=unreadable[requested_row.opportunity_id],
            )
            for index, requested_row in enumerate(requested_rows)
            if requested_row.opportunity_id in unreadable
        }
        for posted_index, posted_outcome in enumerate(posted_outcomes):
            original_index = posted_indexes[posted_index]
            outcomes[original_index] = RecordOutcomeResponse(
                index=original_index,
                record_id=posted_outcome.record_id,
                status=posted_outcome.status,
                error=posted_outcome.error,
            )
        return tuple(outcomes[index] for index in range(record_count))

    def _outcomes(
        self,
        requested_rows: tuple[OpportunityStageHistoryRecordInput, ...],
        stage_ids: tuple[str, ...],
        attributes: BulkOpportunityStageHistoryAttributes,
    ) -> tuple[tuple[RecordOutcomeResponse, ...], tuple[str, ...]]:
        # A history row has no id of its own in the request, so it is matched on the pair it
        # names: the deal and the stage it was moved to.
        return bulk_record_outcomes(
            requested_rows=[
                BulkRequestedRowDto(
                    record_id=requested_row.opportunity_id,
                    match_key=(requested_row.opportunity_id, stage_id),
                )
                for requested_row, stage_id in zip(requested_rows, stage_ids, strict=True)
            ],
            written_keys=[
                pair
                for written_row in attributes.records
                if (pair := self._written_pair(written_row)) is not None
            ],
            summary=attributes.summary(),
        )

    def _written_pair(
        self,
        written_row: BulkOpportunityStageHistoryRecordAttributes,
    ) -> tuple[str, str] | None:
        opportunity_id = written_row.opportunity.resource_id if written_row.opportunity else None
        stage_id = written_row.stage.resource_id if written_row.stage else None
        if opportunity_id is None or stage_id is None:
            return None
        return (opportunity_id, stage_id)
