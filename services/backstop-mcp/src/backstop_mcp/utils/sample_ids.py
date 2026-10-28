from collections.abc import Iterable

_MAX_SAMPLE_IDS = 5


def sample_ids(ids: Iterable[str | None]) -> list[str]:
    """The first few ids for a one-line-per-call warning, so a log line stays bounded."""
    present = [item for item in ids if item is not None]
    return present[:_MAX_SAMPLE_IDS]
