"""Build a `ScanCoverageResponse` from a collection walk's bookkeeping."""

from backstop_mcp.features.collection_scan.responses import ScanCoverageResponse

__all__ = [
    "ERROR_DISCLAIMER",
    "ROW_CAP_DISCLAIMER",
    "scan_coverage",
]

ROW_CAP_DISCLAIMER = (
    "Row bodies were capped at max_rows; more matching records are visible. Raise max_rows "
    "or switch mode to aggregate to count without row bodies."
)
ERROR_DISCLAIMER = (
    "A later page failed; this is a partial scan, not a complete count. Do not treat "
    "aggregates as the full visible set."
)


def _ceiling_disclaimer(ceiling: int) -> str:
    return (
        f"{ceiling} is the most this call will read from the collection, and the scan reached "
        "it, so the true total is unknown — narrow the window or add a filter. A pagination "
        "overrun is not an outage. Counts are visible to you, not firm-wide."
    )


def scan_coverage(
    *,
    rows_scanned: int,
    visible_count: int | None,
    rows_dropped: int,
    ceiling: int,
    ceiling_clamped: bool,
    truncated_by_row_cap: bool,
    partial_due_to_error: bool,
    extra_disclaimers: tuple[str, ...] = (),
) -> ScanCoverageResponse:
    """Coverage for one walk.

    `ceiling` is the most this walk will read: an endpoint wall where there is one (10000 on
    entity-activities) and otherwise the scan ceiling the fetch caps itself at. Both saturate
    the same way from the caller's side — the answer is a prefix of the collection — so both
    are reported as `ceiling_hit`.
    """
    ceiling_hit = ceiling_clamped or visible_count == ceiling
    truncated = truncated_by_row_cap or ceiling_hit or partial_due_to_error
    disclaimers: list[str] = []
    if truncated_by_row_cap:
        disclaimers.append(ROW_CAP_DISCLAIMER)
    if ceiling_hit:
        disclaimers.append(_ceiling_disclaimer(ceiling))
    if partial_due_to_error:
        disclaimers.append(ERROR_DISCLAIMER)
    disclaimers.extend(extra_disclaimers)
    return ScanCoverageResponse(
        rows_scanned=rows_scanned,
        visible_count=visible_count,
        visible_count_is_floor=visible_count == ceiling,
        truncated=truncated,
        ceiling_hit=ceiling_hit,
        partial_due_to_error=partial_due_to_error,
        rows_dropped=rows_dropped,
        disclaimer=" ".join(disclaimers) if disclaimers else None,
    )
