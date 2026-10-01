from datetime import date

import pytest

from backstop_mcp.utils import date_window


class TestDateWindow:
    def test_omitted_start_date_is_one_year_before_end_date(self) -> None:
        since, until = date_window(None, date(2024, 12, 31), today=date(2026, 8, 21))
        assert (since, until) == (date(2023, 12, 31), date(2024, 12, 31))

    def test_leap_day_minus_one_year_lands_on_february_28(self) -> None:
        since, until = date_window(None, date(2024, 2, 29), today=date(2026, 8, 21))
        assert (since, until) == (date(2023, 2, 28), date(2024, 2, 29))

    def test_omitted_end_date_is_today(self) -> None:
        since, until = date_window(date(2025, 8, 21), None, today=date(2026, 8, 21))
        assert (since, until) == (date(2025, 8, 21), date(2026, 8, 21))

    def test_both_dates_omitted_are_the_year_ending_today(self) -> None:
        since, until = date_window(None, None, today=date(2026, 8, 21))
        assert (since, until) == (date(2025, 8, 21), date(2026, 8, 21))

    def test_start_after_end_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="start_date must not be after end_date"):
            date_window(date(2026, 2, 1), date(2026, 1, 1), today=date(2026, 8, 21))
