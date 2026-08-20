"""Scan coverage and aggregate buckets for collection-walking tools.

`search_activities` settles this shape; `search_opportunities` reuses it. Counts are
visible-to-this-credential, not firm-wide, and a truncated or failed walk must say so.
"""

from backstop_mcp.features.collection_scan.internal_dto import AggregateBucketDto
from backstop_mcp.features.collection_scan.responses import (
    AggregateBucketResponse,
    ScanCoverageResponse,
)
from backstop_mcp.features.collection_scan.scan_coverage import (
    ERROR_DISCLAIMER,
    ROW_CAP_DISCLAIMER,
    scan_coverage,
)

__all__ = [
    "AggregateBucketDto",
    "AggregateBucketResponse",
    "ERROR_DISCLAIMER",
    "ROW_CAP_DISCLAIMER",
    "ScanCoverageResponse",
    "scan_coverage",
]
