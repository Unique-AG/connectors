"""Scan coverage and aggregate buckets for collection-walking tools.

`search_activities` settles this shape; `search_opportunities` reuses it. Counts are
visible-to-this-credential, not firm-wide, and a truncated or failed walk must say so.
`project_fields` is the sparse-row projection both tools publish rows through.
`collect_page`, `SearchCursor` and `continuation` page a search's rows: one call returns at most
`SEARCH_RESULT_SIZE` rows and a cursor that resumes at the next unread record.
"""

from backstop_mcp.features.collection_scan.collect_page import (
    CollectedPage,
    StopReason,
    collect_page,
)
from backstop_mcp.features.collection_scan.continuation import continuation
from backstop_mcp.features.collection_scan.internal_dto import AggregateBucketDto
from backstop_mcp.features.collection_scan.project_fields import project_fields
from backstop_mcp.features.collection_scan.responses import (
    AggregateBucketResponse,
    ContinuationResponse,
    ScanCoverageResponse,
)
from backstop_mcp.features.collection_scan.scan_coverage import (
    ERROR_DISCLAIMER,
    scan_coverage,
)
from backstop_mcp.features.collection_scan.search_cursor import (
    InvalidCursorError,
    SearchCursor,
    search_fingerprint,
)

__all__ = [
    "InvalidCursorError",
    "AggregateBucketDto",
    "AggregateBucketResponse",
    "CollectedPage",
    "ContinuationResponse",
    "ERROR_DISCLAIMER",
    "ScanCoverageResponse",
    "SearchCursor",
    "StopReason",
    "collect_page",
    "continuation",
    "project_fields",
    "scan_coverage",
    "search_fingerprint",
]
