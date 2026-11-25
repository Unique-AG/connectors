from datetime import datetime
from zoneinfo import ZoneInfo

from office_365_mcp.shared.window import runs_backwards


def test_a_window_across_the_repeated_hour_is_not_backwards() -> None:
    new_york = ZoneInfo("America/New_York")
    after = datetime.fromisoformat("2026-11-01T01:45:00-04:00")
    before = datetime.fromisoformat("2026-11-01T01:15:00-05:00")

    assert not runs_backwards(after, before, zone=new_york)


def test_a_later_lower_bound_is_backwards() -> None:
    after = datetime.fromisoformat("2026-11-02T10:00:00+00:00")
    before = datetime.fromisoformat("2026-11-02T09:00:00+00:00")

    assert runs_backwards(after, before)
