from collections.abc import Generator
from contextlib import contextmanager


class CaseLocks:
    """One lock per case that refuses a second holder instead of waiting for the first.

    Waiting would let a write that was approved against an earlier state run after it.
    """

    def __init__(self) -> None:
        self._held: set[str] = set()

    @contextmanager
    def hold(self, case_system_id: str, *, refuse: Exception) -> Generator[None]:
        if case_system_id in self._held:
            raise refuse
        self._held.add(case_system_id)
        try:
            yield
        finally:
            self._held.discard(case_system_id)
