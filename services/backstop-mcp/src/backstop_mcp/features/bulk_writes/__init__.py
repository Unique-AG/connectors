"""The `POST /bulk-*` route family: its summary shape and the fold from a `201` to outcomes.

A bulk write answers `201` whether or not anything landed, so every feature that posts one
needs the same reading of `bulkLoadSummary`. It lives here once rather than per feature.
"""

from backstop_mcp.features.bulk_writes.api_responses import (
    BulkLoadErrorMessageAttributes,
    BulkLoadSummaryAttributes,
)
from backstop_mcp.features.bulk_writes.bulk_record_outcomes import bulk_record_outcomes
from backstop_mcp.features.bulk_writes.internal_dto import BulkRequestedRowDto
from backstop_mcp.features.bulk_writes.responses import RecordOutcomeResponse

__all__ = [
    "BulkLoadErrorMessageAttributes",
    "BulkLoadSummaryAttributes",
    "BulkRequestedRowDto",
    "RecordOutcomeResponse",
    "bulk_record_outcomes",
]
