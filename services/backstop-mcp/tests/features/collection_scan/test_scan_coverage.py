from backstop_mcp.features.collection_scan import (
    ERROR_DISCLAIMER,
    ROW_CAP_DISCLAIMER,
    scan_coverage,
)


class TestScanCoverage:
    def test_a_complete_walk_has_no_disclaimer(self) -> None:
        coverage = scan_coverage(
            rows_scanned=3,
            visible_count=3,
            rows_dropped=0,
            ceiling=10_000,
            ceiling_clamped=False,
            truncated_by_row_cap=False,
            partial_due_to_error=False,
        )

        assert coverage.truncated is False
        assert coverage.ceiling_hit is False
        assert coverage.visible_count_is_floor is False
        assert coverage.partial_due_to_error is False
        assert coverage.disclaimer is None

    def test_a_saturated_count_is_a_floor(self) -> None:
        coverage = scan_coverage(
            rows_scanned=500,
            visible_count=10_000,
            rows_dropped=0,
            ceiling=10_000,
            ceiling_clamped=False,
            truncated_by_row_cap=False,
            partial_due_to_error=False,
        )

        assert coverage.visible_count_is_floor is True
        assert coverage.ceiling_hit is True
        assert coverage.truncated is True
        assert coverage.disclaimer is not None
        assert "10000" in coverage.disclaimer

    def test_a_later_page_failure_is_partial_not_a_row_cap(self) -> None:
        coverage = scan_coverage(
            rows_scanned=500,
            visible_count=2000,
            rows_dropped=0,
            ceiling=10_000,
            ceiling_clamped=False,
            truncated_by_row_cap=False,
            partial_due_to_error=True,
        )

        assert coverage.partial_due_to_error is True
        assert coverage.truncated is True
        assert coverage.disclaimer == ERROR_DISCLAIMER
        assert ROW_CAP_DISCLAIMER not in (coverage.disclaimer or "")
