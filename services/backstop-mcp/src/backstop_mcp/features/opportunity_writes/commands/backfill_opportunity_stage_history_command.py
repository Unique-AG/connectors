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

_OpportunityAndStage = tuple[str, str]


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
            stage_ids: list[str] = []
            for requested_row in backfill.records:
                stage = await self._opportunity_stages_service.find_by_stage_name(
                    name=requested_row.stage
                )
                stage_ids.append(stage.id)
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
                        for requested_row, stage_id in zip(backfill.records, stage_ids, strict=True)
                    ]
                },
            )
            document = await self._client.post(
                "/bulk-opportunity-stage-history",
                schema=BulkOpportunityStageHistoryDocument,
                json=payload,
            )
            outcomes = self._outcomes(backfill.records, tuple(stage_ids), document.data.attributes)
            applied_count = sum(1 for outcome in outcomes if outcome.status == "applied")
            logger.info(
                "opportunity_writes.stage_history.backfilled",
                extra={
                    "total_count": len(outcomes),
                    "applied_count": applied_count,
                    "failed_count": len(outcomes) - applied_count,
                },
            )
            return BackfillOpportunityStageHistoryResponse(
                total_count=len(outcomes),
                applied_count=applied_count,
                records=outcomes,
            )

    def _outcomes(
        self,
        requested_rows: tuple[OpportunityStageHistoryRecordInput, ...],
        stage_ids: tuple[str, ...],
        attributes: BulkOpportunityStageHistoryAttributes,
    ) -> tuple[RecordOutcomeResponse, ...]:
        summary = attributes.summary()
        error_by_index = {
            message.index: message.message
            for message in summary.error_messages
            if message.index is not None
        }
        batch_error = next(
            (
                message.message
                for message in summary.error_messages
                if message.index is None and message.message
            ),
            None,
        )
        unmatched_written = self._written_opportunity_and_stage(attributes.records)
        batch_failed = summary.success_count == 0
        unreturned_error = batch_error or (
            "Backstop did not return this row among the written records."
        )
        batch_failed_error = batch_error or "Backstop reported successCount 0 for this batch."
        outcomes: list[RecordOutcomeResponse] = []
        for index, (requested_row, stage_id) in enumerate(
            zip(requested_rows, stage_ids, strict=True)
        ):
            if index in error_by_index or batch_failed:
                outcomes.append(
                    RecordOutcomeResponse(
                        index=index,
                        record_id=requested_row.opportunity_id,
                        status="failed",
                        error=error_by_index.get(index) or batch_failed_error,
                    )
                )
                continue
            remaining_written = self._without_matching_row(
                unmatched_written, (requested_row.opportunity_id, stage_id)
            )
            if remaining_written is None:
                outcomes.append(
                    RecordOutcomeResponse(
                        index=index,
                        record_id=requested_row.opportunity_id,
                        status="failed",
                        error=unreturned_error,
                    )
                )
                continue
            unmatched_written = remaining_written
            outcomes.append(
                RecordOutcomeResponse(
                    index=index,
                    record_id=requested_row.opportunity_id,
                    status="applied",
                    error=None,
                )
            )
        return tuple(outcomes)

    def _written_opportunity_and_stage(
        self,
        written_rows: list[BulkOpportunityStageHistoryRecordAttributes],
    ) -> tuple[_OpportunityAndStage, ...]:
        pairs: list[_OpportunityAndStage] = []
        for written_row in written_rows:
            opportunity_id = (
                written_row.opportunity.resource_id if written_row.opportunity else None
            )
            stage_id = written_row.stage.resource_id if written_row.stage else None
            if opportunity_id is None or stage_id is None:
                continue
            pairs.append((opportunity_id, stage_id))
        return tuple(pairs)

    def _without_matching_row(
        self,
        written_pairs: tuple[_OpportunityAndStage, ...],
        requested_pair: _OpportunityAndStage,
    ) -> tuple[_OpportunityAndStage, ...] | None:
        for index, written_pair in enumerate(written_pairs):
            if written_pair == requested_pair:
                return written_pairs[:index] + written_pairs[index + 1 :]
        return None
