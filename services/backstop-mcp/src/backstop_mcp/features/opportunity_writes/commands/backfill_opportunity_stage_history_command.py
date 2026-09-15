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
            outcomes, warnings = self._outcomes(
                backfill.records, tuple(stage_ids), document.data.attributes
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

    def _outcomes(
        self,
        requested_rows: tuple[OpportunityStageHistoryRecordInput, ...],
        stage_ids: tuple[str, ...],
        attributes: BulkOpportunityStageHistoryAttributes,
    ) -> tuple[tuple[RecordOutcomeResponse, ...], tuple[str, ...]]:
        summary = attributes.summary()
        error_by_index = {
            message.index: message.message
            or f"Backstop reported an error for record #{message.index} without a message."
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
        written_pairs = [
            pair
            for written_row in attributes.records
            if (pair := self._written_pair(written_row)) is not None
        ]
        outcomes: list[RecordOutcomeResponse] = []
        for index, (requested_row, stage_id) in enumerate(
            zip(requested_rows, stage_ids, strict=True)
        ):
            pair = (requested_row.opportunity_id, stage_id)
            if index in error_by_index:
                error: str | None = error_by_index[index]
            elif summary.success_count == 0:
                error = batch_error or "Backstop reported successCount 0 for this batch."
            elif pair in written_pairs:
                written_pairs.remove(pair)
                error = None
            else:
                error = batch_error or (
                    "Backstop did not return this row among the written records."
                )
            outcomes.append(
                RecordOutcomeResponse(
                    index=index,
                    record_id=requested_row.opportunity_id,
                    status="failed" if error else "applied",
                    error=error,
                )
            )
        reported = {outcome.error for outcome in outcomes if outcome.error}
        warnings = tuple(
            message.message
            for message in summary.error_messages
            if message.message and message.message not in reported
        )
        return tuple(outcomes), warnings

    def _written_pair(
        self,
        written_row: BulkOpportunityStageHistoryRecordAttributes,
    ) -> tuple[str, str] | None:
        opportunity_id = written_row.opportunity.resource_id if written_row.opportunity else None
        stage_id = written_row.stage.resource_id if written_row.stage else None
        if opportunity_id is None or stage_id is None:
            return None
        return (opportunity_id, stage_id)
