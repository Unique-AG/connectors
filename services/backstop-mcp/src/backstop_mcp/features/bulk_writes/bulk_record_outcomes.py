"""Attribute a bulk `201` back to the rows that were sent.

Backstop answers a bulk write with a summary (`successCount`, `errorMessages`) and the rows it
actually landed; failed rows are simply absent. Error messages carry a 0-based `index` when
Backstop could attribute them, and none when it could not. A row is `applied` only when it is
not named by an error, the batch did not fail wholesale, and its key came back among the
landed records — anything else is `failed` with the best message available.
"""

from collections.abc import Sequence

from backstop_mcp.features.bulk_writes.api_responses import BulkLoadSummaryAttributes
from backstop_mcp.features.bulk_writes.internal_dto import BulkRequestedRowDto
from backstop_mcp.features.bulk_writes.responses import RecordOutcomeResponse

__all__ = ["bulk_record_outcomes"]


def bulk_record_outcomes(
    *,
    requested_rows: Sequence[BulkRequestedRowDto],
    written_keys: Sequence[object],
    summary: BulkLoadSummaryAttributes,
) -> tuple[tuple[RecordOutcomeResponse, ...], tuple[str, ...]]:
    """Per-row outcomes in request order, plus the messages no row could claim."""
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
    # One landed record claims one request row: a batch may legitimately repeat a key.
    unclaimed_keys = list(written_keys)
    outcomes: list[RecordOutcomeResponse] = []
    for index, requested_row in enumerate(requested_rows):
        if index in error_by_index:
            error: str | None = error_by_index[index]
        elif summary.success_count == 0:
            error = batch_error or "Backstop reported successCount 0 for this batch."
        elif requested_row.match_key in unclaimed_keys:
            unclaimed_keys.remove(requested_row.match_key)
            error = None
        else:
            error = batch_error or "Backstop did not return this row among the written records."
        outcomes.append(
            RecordOutcomeResponse(
                index=index,
                record_id=requested_row.record_id,
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
