"""POST `/bulk-opportunity-stage-history`. Appends history rows; does not move a deal's stage."""

import logging

from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopClient,
    isoformat,
    json_api_create,
    resource_pointer,
)
from backstop_mcp.features.bulk_writes import (
    BulkRequestedRowDto,
    RecordOutcomeResponse,
    bulk_record_outcomes,
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
