from datetime import date

from backstop_mcp.features.accounts import AccountSpanDto, TenureDto, continuous_tenure

_TODAY = date(2026, 10, 8)


def _closed(start: date | None, end: date | None) -> AccountSpanDto:
    return AccountSpanDto(start=start, end=end, is_open=False)


def _open(start: date | None) -> AccountSpanDto:
    return AccountSpanDto(start=start, end=None, is_open=True)


class TestContinuousTenure:
    def test_rotating_accounts_chain_back_past_every_open_account(self) -> None:
        # The live Syz Capital shape: no open account is older than 2019, the run is from 2008.
        spans = (
            _closed(date(2008, 8, 1), date(2016, 1, 1)),
            _closed(date(2014, 6, 1), date(2021, 4, 1)),
            _closed(date(2016, 1, 1), date(2023, 3, 31)),
            _open(date(2019, 6, 1)),
            _open(date(2024, 11, 1)),
        )

        assert continuous_tenure(spans, today=_TODAY) == TenureDto(
            continuous_since=date(2008, 8, 1)
        )

    def test_a_gap_starts_a_new_run(self) -> None:
        # The live BlackRock shape: in 2007-2009, out, back in 2025.
        spans = (
            _closed(date(2007, 8, 1), date(2009, 6, 30)),
            _open(date(2025, 3, 1)),
        )

        assert continuous_tenure(spans, today=_TODAY).continuous_since == date(2025, 3, 1)

    def test_close_on_the_last_day_and_open_on_the_next_is_one_run(self) -> None:
        spans = (_closed(date(2012, 1, 1), date(2015, 12, 31)), _open(date(2016, 1, 1)))

        assert continuous_tenure(spans, today=_TODAY).continuous_since == date(2012, 1, 1)

    def test_a_one_day_hole_breaks_the_run(self) -> None:
        spans = (_closed(date(2012, 1, 1), date(2015, 12, 30)), _open(date(2016, 1, 1)))

        assert continuous_tenure(spans, today=_TODAY).continuous_since == date(2016, 1, 1)

    def test_an_owner_whose_accounts_are_all_closed_has_no_tenure(self) -> None:
        spans = (_closed(date(2012, 3, 1), date(2025, 3, 31)),)

        assert continuous_tenure(spans, today=_TODAY).continuous_since is None

    def test_an_account_closing_after_today_is_still_held(self) -> None:
        spans = (_closed(date(2020, 1, 1), date(2026, 12, 31)),)

        assert continuous_tenure(spans, today=_TODAY).continuous_since == date(2020, 1, 1)

    def test_an_account_that_has_not_started_yet_is_not_tenure(self) -> None:
        spans = (_open(date(2027, 1, 1)),)

        assert continuous_tenure(spans, today=_TODAY).continuous_since is None

    def test_a_future_account_does_not_replace_the_run_covering_today(self) -> None:
        spans = (_closed(date(2015, 1, 1), date(2026, 12, 31)), _open(date(2027, 6, 1)))

        assert continuous_tenure(spans, today=_TODAY).continuous_since == date(2015, 1, 1)

    def test_closed_with_no_closed_date_is_undated_not_open(self) -> None:
        # Reading the missing end as "open" would stretch this owner's tenure back to 2010.
        spans = (_closed(date(2010, 1, 1), None), _open(date(2020, 1, 1)))

        assert continuous_tenure(spans, today=_TODAY) == TenureDto(
            continuous_since=date(2020, 1, 1), undated_accounts=1
        )

    def test_accounts_with_no_start_are_counted_and_left_out(self) -> None:
        spans = (_open(None), _closed(None, date(2025, 9, 30)))

        assert continuous_tenure(spans, today=_TODAY) == TenureDto(undated_accounts=2)
