from datetime import date, datetime, time

from backstop_mcp.dates import parse_lenient_date, parse_lenient_datetime


class TestParseLenientDate:
    def test_iso_date(self) -> None:
        assert parse_lenient_date("2026-01-15") == date(2026, 1, 15)

    def test_unpadded_date(self) -> None:
        assert parse_lenient_date("2026-9-1") == date(2026, 9, 1)

    def test_junk_is_none(self) -> None:
        assert parse_lenient_date("not-a-date") is None

    def test_blank_is_none(self) -> None:
        assert parse_lenient_date("  ") is None

    def test_none_is_none(self) -> None:
        assert parse_lenient_date(None) is None

    def test_us_month_day_year(self) -> None:
        assert parse_lenient_date("8/3/2026") == date(2026, 8, 3)

    def test_us_zero_padded_month_day_year(self) -> None:
        assert parse_lenient_date("08/03/2026") == date(2026, 8, 3)

    def test_a_two_digit_year_is_not_the_year_26_ad(self) -> None:
        assert parse_lenient_date("1/1/26") is None


class TestParseLenientDatetime:
    def test_backstop_offset_without_colon(self) -> None:
        parsed = parse_lenient_datetime("2026-01-10T00:00:00.000-0500")

        assert parsed is not None
        assert parsed == datetime.fromisoformat("2026-01-10T00:00:00-05:00")

    def test_date_becomes_midnight(self) -> None:
        assert parse_lenient_datetime(date(2026, 1, 10)) == datetime.combine(
            date(2026, 1, 10), time.min
        )

    def test_junk_is_none(self) -> None:
        assert parse_lenient_datetime("not-a-datetime") is None

    def test_unix_timestamp_number_is_none(self) -> None:
        assert parse_lenient_datetime(1) is None

    def test_blank_is_none(self) -> None:
        assert parse_lenient_datetime("") is None

    def test_us_date_becomes_midnight(self) -> None:
        assert parse_lenient_datetime("8/3/2026") == datetime.combine(date(2026, 8, 3), time.min)
