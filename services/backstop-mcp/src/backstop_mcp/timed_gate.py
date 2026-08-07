"""Wall-clock duration gate for freshness / cooldown / refresh-floor checks."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass
class TimedGate:
    """Tracks whether a stamped instant is still within a fixed duration."""

    duration: timedelta
    marked_at: datetime | None = field(default=None, repr=False)

    def within(self) -> bool:
        if self.marked_at is None:
            return False
        return datetime.now(UTC) - self.marked_at < self.duration

    def mark(self, when: datetime | None = None) -> None:
        self.marked_at = when if when is not None else datetime.now(UTC)

    def clear(self) -> None:
        self.marked_at = None

    def clear_if_expired(self) -> None:
        if self.marked_at is not None and not self.within():
            self.marked_at = None
