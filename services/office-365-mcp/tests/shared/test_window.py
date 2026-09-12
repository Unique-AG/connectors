"""`shared/window.py`: the one rule every windowed tool on the surface agrees on.

The rule is that the bound a caller names is inside the window. Five tools depend on it across
three unrelated Graph surfaces, so it is pinned here rather than five times over in their own
files — and the two traps below are the ones that made a shared module worth having.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from office_365_mcp.shared.window import as_utc, closes_at, opens_at, runs_backwards

_CET = timezone(timedelta(hours=2))


class TestWhatABoundMeans:
    def test_a_date_opens_at_its_first_instant(self) -> None:
        assert opens_at(date(2026, 3, 4)) == datetime(2026, 3, 4, 0, 0, tzinfo=UTC)

    def test_a_date_closes_at_its_last_instant_and_not_its_first(self) -> None:
        """Two first instants would bracket nothing, which is a caller's most obvious way to ask
        for a single day — and an empty answer nobody can see through."""
        closed = closes_at(date(2026, 3, 4))

        assert closed.date() == date(2026, 3, 4)
        assert closed > opens_at(date(2026, 3, 4))
        assert closed < opens_at(date(2026, 3, 5))

    def test_a_moment_is_itself_at_either_end(self) -> None:
        moment = datetime(2026, 3, 4, 9, 15, tzinfo=UTC)

        assert opens_at(moment) == moment
        assert closes_at(moment) == moment

    @pytest.mark.parametrize("resolve", [opens_at, closes_at])
    def test_a_datetime_is_read_as_a_moment_and_not_as_the_day_it_falls_on(
        self, resolve: Callable[[date | datetime], datetime]
    ) -> None:
        """`datetime` subclasses `date`, so a type check in the wrong order silently discards the
        time. Both directions of that mistake land on midnight, which is why it is asserted."""
        resolved = resolve(datetime(2026, 3, 4, 9, 15, tzinfo=UTC))

        assert (resolved.hour, resolved.minute) == (9, 15)


class TestTheZoneItResolvesAgainst:
    def test_a_naive_moment_is_read_as_utc_and_not_as_local_time(self) -> None:
        """Local time is whichever zone the process runs in — one no caller chose."""
        assert opens_at(datetime(2026, 3, 4, 9, 0)) == datetime(2026, 3, 4, 9, 0, tzinfo=UTC)

    def test_an_offset_the_caller_wrote_is_converted_rather_than_dropped(self) -> None:
        """09:00+02:00 is 07:00 UTC. This is the half `as_utc` does NOT do, and rendering its
        result with a trailing `Z` is what moves a bound by the offset."""
        assert opens_at(datetime(2026, 3, 4, 9, 0, tzinfo=_CET)) == datetime(
            2026, 3, 4, 7, 0, tzinfo=UTC
        )
        assert closes_at(datetime(2026, 3, 4, 9, 0, tzinfo=_CET)) == datetime(
            2026, 3, 4, 7, 0, tzinfo=UTC
        )

    def test_as_utc_labels_a_naive_moment_and_leaves_an_aware_one_alone(self) -> None:
        """Pinned because it is the documented trap: correct for comparing, wrong for rendering."""
        aware = datetime(2026, 3, 4, 9, 0, tzinfo=_CET)

        assert as_utc(datetime(2026, 3, 4, 9, 0)).tzinfo == UTC
        assert as_utc(aware) is aware


class TestAWindowThatHoldsNothing:
    def test_two_dates_the_wrong_way_round_run_backwards(self) -> None:
        assert runs_backwards(date(2026, 3, 31), date(2026, 3, 1)) is True

    def test_one_date_in_both_bounds_is_a_day_and_not_backwards(self) -> None:
        assert runs_backwards(date(2026, 3, 4), date(2026, 3, 4)) is False

    def test_consecutive_dates_the_wrong_way_round_are_caught(self) -> None:
        """The tight case: a tool rendering the upper bound as `lt` the NEXT day would compare
        these two as equal and let a backwards window through."""
        assert runs_backwards(date(2026, 3, 5), date(2026, 3, 4)) is True

    def test_a_date_and_a_moment_are_compared_rather_than_refused(self) -> None:
        """Python raises `TypeError` on `date < datetime`, so the shapes have to be resolved to
        instants before they can be ordered at all."""
        assert runs_backwards(datetime(2026, 3, 31, 9, 0, tzinfo=UTC), date(2026, 3, 1)) is True
        assert runs_backwards(date(2026, 3, 1), datetime(2026, 3, 31, 9, 0, tzinfo=UTC)) is False

    def test_a_moment_inside_the_upper_bounds_own_day_is_not_backwards(self) -> None:
        """The upper date closes at the END of its day, so a morning moment on that same day is
        still inside it."""
        assert runs_backwards(datetime(2026, 3, 4, 9, 0, tzinfo=UTC), date(2026, 3, 4)) is False

    def test_one_moment_in_both_bounds_names_that_instant(self) -> None:
        moment = datetime(2026, 3, 4, 9, 15, tzinfo=UTC)

        assert runs_backwards(moment, moment) is False

    @pytest.mark.parametrize(
        ("after", "before"),
        [(None, None), (date(2026, 3, 4), None), (None, date(2026, 3, 4))],
    )
    def test_a_half_open_window_never_runs_backwards(
        self, after: date | None, before: date | None
    ) -> None:
        assert runs_backwards(after, before) is False
