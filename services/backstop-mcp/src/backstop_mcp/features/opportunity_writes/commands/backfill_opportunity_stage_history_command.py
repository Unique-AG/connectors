"""POST `/bulk-opportunity-stage-history`. Appends history rows; does not move a deal's stage."""

import logging

from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopClient,
    isoformat,
    json_api_create,
    resource_pointer,
)
from backstop_mcp.features.opportunities import OpportunityStagesService
from backstop_mcp.features.opportunity_writes.api_responses import (
    BulkOpportunityStageHistoryAttributes,
    BulkOpportunityStageHistoryDocument,
    BulkOpportunityStageHistoryRecordAttributes,
)
from backstop_mcp.features.opportunity_writes.backfill_opportunity_stage_history_input import (
    BackfillOpportunityStageHistoryInput,
    OpportunityStageHistoryRecordInput,
)
from backstop_mcp.features.opportunity_writes.responses import (
    BackfillOpportunityStageHistoryResponse,
    RecordOutcomeResponse,
)

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_LandedKey = tuple[str, str]


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
            resolved: list[str] = []
            for record in backfill.records:
                stage = await self._opportunity_stages_service.find_by_stage_name(name=record.stage)
                resolved.append(stage.id)
            payload = json_api_create(
                resource_type="bulk-opportunity-stage-history",
                attributes={
                    "records": [
                        {
                            "effectiveDate": isoformat(record.effective_date),
                            "opportunity": resource_pointer(
                                resource_id=record.opportunity_id,
                                resource_type="opportunities",
                            ),
                            "stage": resource_pointer(
                                resource_id=stage_id, resource_type="opportunity-stages"
                            ),
                        }
                        for record, stage_id in zip(backfill.records, resolved, strict=True)
                    ]
                },
            )
            document = await self._client.post(
                "/bulk-opportunity-stage-history",
                schema=BulkOpportunityStageHistoryDocument,
                json=payload,
            )
            records = self._outcomes(backfill.records, tuple(resolved), document.data.attributes)
            applied = sum(1 for record in records if record.status == "applied")
            logger.info(
                "opportunity_writes.stage_history.backfilled",
                extra={
                    "total_count": len(records),
                    "applied_count": applied,
                    "failed_count": len(records) - applied,
                },
            )
            return BackfillOpportunityStageHistoryResponse(
                total_count=len(records),
                applied_count=applied,
                records=records,
            )

    def _outcomes(
        self,
        records: tuple[OpportunityStageHistoryRecordInput, ...],
        stage_ids: tuple[str, ...],
        attributes: BulkOpportunityStageHistoryAttributes,
    ) -> tuple[RecordOutcomeResponse, ...]:
        summary = attributes.summary()
        errors = {
            message.index: message.message
            for message in summary.error_messages
            if message.index is not None
        }
        unindexed = next(
            (
                message.message
                for message in summary.error_messages
                if message.index is None and message.message
            ),
            None,
        )
        leftover = _landed_keys(attributes.records)
        nothing_written = summary.success_count == 0
        missing_row = unindexed or ("Backstop did not return this row among the written records.")
        fallback = unindexed or "Backstop reported successCount 0 for this batch."
        outcomes: list[RecordOutcomeResponse] = []
        for index, (record, stage_id) in enumerate(zip(records, stage_ids, strict=True)):
            if index in errors or nothing_written:
                outcomes.append(
                    RecordOutcomeResponse(
                        index=index,
                        record_id=record.opportunity_id,
                        status="failed",
                        error=errors.get(index) or fallback,
                    )
                )
                continue
            consumed = _without_first(leftover, (record.opportunity_id, stage_id))
            if consumed is None:
                outcomes.append(
                    RecordOutcomeResponse(
                        index=index,
                        record_id=record.opportunity_id,
                        status="failed",
                        error=missing_row,
                    )
                )
                continue
            leftover = consumed
            outcomes.append(
                RecordOutcomeResponse(
                    index=index,
                    record_id=record.opportunity_id,
                    status="applied",
                    error=None,
                )
            )
        return tuple(outcomes)


def _landed_keys(
    records: list[BulkOpportunityStageHistoryRecordAttributes],
) -> tuple[_LandedKey, ...]:
    keys: list[_LandedKey] = []
    for record in records:
        opportunity_id = record.opportunity.resource_id if record.opportunity else None
        stage_id = record.stage.resource_id if record.stage else None
        if opportunity_id is None or stage_id is None:
            continue
        keys.append((opportunity_id, stage_id))
    return tuple(keys)


def _without_first(keys: tuple[_LandedKey, ...], key: _LandedKey) -> tuple[_LandedKey, ...] | None:
    for index, item in enumerate(keys):
        if item == key:
            return keys[:index] + keys[index + 1 :]
    return None
