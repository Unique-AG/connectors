"""Turn a collected page's stop into the `continuation` a paged search returns."""

from collections.abc import Sequence

from backstop_mcp.features.collection_scan.collect_page import StopReason
from backstop_mcp.features.collection_scan.responses import ContinuationResponse
from backstop_mcp.features.collection_scan.search_cursor import SearchCursor

__all__ = ["continuation"]


def continuation(
    *,
    stop_reason: StopReason,
    next_offsets: Sequence[int],
    fingerprint: str,
    rows_returned: int,
) -> ContinuationResponse | None:
    """`None` when the result set is complete."""
    if stop_reason != "page_full":
        return None
    return ContinuationResponse(
        cursor=SearchCursor(offsets=tuple(next_offsets), fingerprint=fingerprint).encode(),
        message=(
            f"Stopped at {rows_returned} rows, the most one search call returns. More rows may "
            "match: call again with this cursor and the same arguments for the next page. There "
            "is no limit argument to raise."
        ),
    )
