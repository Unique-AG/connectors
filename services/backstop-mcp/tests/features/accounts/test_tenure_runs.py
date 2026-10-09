from datetime import date

from backstop_mcp.features.accounts import AccountSpanDto, TenureDto, TenureRunDto, tenure_runs
from tests.features.accounts.conftest import TODAY as _TODAY


def _closed(start: date | None, end: date | None) -> AccountSpanDto:
    return AccountSpanDto(start=start, end=end, is_open=False)


def _open(start: date | None) -> AccountSpanDto:
    return AccountSpanDto(start=start, end=None, is_open=True)


def _bounds(tenure: TenureDto) -> list[tuple[date, date | None]]:
    return [(run.start, run.end) for run in tenure.runs]


class TestTenureRuns:
    def test_rotating_accounts_chain_back_past_every_open_account(self) -> None:
        # A rotating private bank: no open account is older than 2019, the run is from 2008.
        spans = (
            _closed(date(2008, 8, 1), date(2016, 1, 1)),
            _closed(date(2014, 6, 1), date(2021, 4, 1)),
            _closed(date(2016, 1, 1), date(2023, 3, 31)),
            _open(date(2019, 6, 1)),
            _open(date(2024, 11, 1)),
        )

        assert tenure_runs(spans, today=_TODAY) == TenureDto(
            runs=(TenureRunDto(start=date(2008, 8, 1), end=None, years=18.18),)
        )

    def test_a_gap_starts_a_new_run_and_both_are_kept(self) -> None:
        # In 2007-2009, out, back in 2025. The older run is longer.
        spans = (
            _closed(date(2007, 8, 1), date(2009, 6, 30)),
            _open(date(2025, 3, 1)),
        )

        assert tenure_runs(spans, today=_TODAY) == TenureDto(
            runs=(
                TenureRunDto(start=date(2007, 8, 1), end=date(2009, 6, 30), years=1.91),
                TenureRunDto(start=date(2025, 3, 1), end=None, years=1.6),
            )
        )

    def test_a_years_long_break_is_not_bridged(self) -> None:
        # A hedge for two years, a break of several, then back: two runs, not one.
        spans = (
            _closed(date(2015, 1, 1), date(2016, 12, 31)),
            _closed(date(2021, 1, 1), date(2024, 6, 30)),
        )

        assert _bounds(tenure_runs(spans, today=_TODAY)) == [
            (date(2021, 1, 1), date(2024, 6, 30)),
            (date(2015, 1, 1), date(2016, 12, 31)),
        ]

    def test_close_on_the_last_day_and_open_on_the_next_is_one_run(self) -> None:
        spans = (_closed(date(2012, 1, 1), date(2015, 12, 31)), _open(date(2016, 1, 1)))

        assert _bounds(tenure_runs(spans, today=_TODAY)) == [(date(2012, 1, 1), None)]

    def test_a_one_day_hole_breaks_the_run(self) -> None:
        spans = (_closed(date(2012, 1, 1), date(2015, 12, 30)), _open(date(2016, 1, 1)))

        assert _bounds(tenure_runs(spans, today=_TODAY)) == [
            (date(2016, 1, 1), None),
            (date(2012, 1, 1), date(2015, 12, 30)),
        ]

    def test_an_owner_whose_accounts_are_all_closed_keeps_its_run(self) -> None:
        # A former investor is still the longest-standing one under some readings.
        spans = (_closed(date(2012, 3, 1), date(2025, 3, 31)),)

        assert tenure_runs(spans, today=_TODAY) == TenureDto(
            runs=(TenureRunDto(start=date(2012, 3, 1), end=date(2025, 3, 31), years=13.08),)
        )

    def test_overlapping_closed_accounts_merge_without_an_open_one(self) -> None:
        spans = (
            _closed(date(2010, 1, 1), date(2014, 12, 31)),
            _closed(date(2013, 6, 1), date(2019, 6, 30)),
        )

        assert _bounds(tenure_runs(spans, today=_TODAY)) == [(date(2010, 1, 1), date(2019, 6, 30))]

    def test_an_account_closing_after_today_keeps_its_end_and_counts_only_to_today(
        self,
    ) -> None:
        spans = (_closed(date(2020, 1, 1), date(2026, 12, 31)),)

        assert tenure_runs(spans, today=_TODAY) == TenureDto(
            runs=(TenureRunDto(start=date(2020, 1, 1), end=date(2026, 12, 31), years=6.77),)
        )

    def test_an_account_that_has_not_started_yet_is_not_tenure(self) -> None:
        spans = (_open(date(2027, 1, 1)),)

        assert tenure_runs(spans, today=_TODAY) == TenureDto()

    def test_a_future_account_after_a_gap_does_not_add_a_run(self) -> None:
        spans = (_closed(date(2015, 1, 1), date(2026, 12, 31)), _open(date(2027, 6, 1)))

        assert _bounds(tenure_runs(spans, today=_TODAY)) == [(date(2015, 1, 1), date(2026, 12, 31))]

    def test_a_booked_rollover_continues_the_run_held_today(self) -> None:
        # The successor opens after today, the day after the current account closes.
        spans = (_closed(date(2015, 1, 1), date(2026, 12, 31)), _open(date(2027, 1, 1)))

        assert tenure_runs(spans, today=_TODAY) == TenureDto(
            runs=(TenureRunDto(start=date(2015, 1, 1), end=None, years=11.77),)
        )

    def test_equal_length_runs_put_the_more_recent_first(self) -> None:
        # Both 181 days: neither crosses a leap day, so only the tie-break orders them.
        spans = (
            _closed(date(2010, 1, 1), date(2010, 7, 1)),
            _closed(date(2021, 1, 1), date(2021, 7, 1)),
        )

        assert [run.start for run in tenure_runs(spans, today=_TODAY).runs] == [
            date(2021, 1, 1),
            date(2010, 1, 1),
        ]

    def test_closed_with_no_closed_date_is_undated_not_open(self) -> None:
        # Reading the missing end as "open" would stretch this owner's tenure back to 2010.
        spans = (_closed(date(2010, 1, 1), None), _open(date(2020, 1, 1)))

        assert tenure_runs(spans, today=_TODAY) == TenureDto(
            runs=(TenureRunDto(start=date(2020, 1, 1), end=None, years=6.77),),
            undated_accounts=1,
        )

    def test_closed_before_it_started_is_undated(self) -> None:
        # A data-entry slip would otherwise publish a run with negative years.
        spans = (_closed(date(2020, 5, 1), date(2020, 1, 1)),)

        assert tenure_runs(spans, today=_TODAY) == TenureDto(undated_accounts=1)

    def test_accounts_with_no_start_are_counted_and_left_out(self) -> None:
        spans = (_open(None), _closed(None, date(2025, 9, 30)))

        assert tenure_runs(spans, today=_TODAY) == TenureDto(undated_accounts=2)
