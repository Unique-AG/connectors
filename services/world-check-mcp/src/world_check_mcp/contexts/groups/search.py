from difflib import SequenceMatcher

from world_check_mcp.contexts.groups.models import GroupEntry

_MINIMUM_SCORE = 0.75


def find_groups(
    groups: list[GroupEntry], *, query: str | None, parent_id: str | None
) -> list[GroupEntry]:
    """The groups under `parent_id` that `query` names, best match first.

    A name that holds every word of the query matches, and so does one that is close to it, so a
    typo still finds the group.
    """
    candidates = [group for group in groups if parent_id is None or group.parent_id == parent_id]
    if query is None:
        return candidates
    needle = _folded(text=query)
    scored = [(_score(needle=needle, group=group), group) for group in candidates]
    kept = [(score, group) for score, group in scored if score >= _MINIMUM_SCORE]
    return [
        group for _, group in sorted(kept, key=lambda item: (-item[0], _folded(text=item[1].name)))
    ]


def _score(*, needle: str, group: GroupEntry) -> float:
    name = _folded(text=group.name)
    if needle == name or needle == _folded(text=group.id):
        return 1.0
    if name.startswith(needle):
        return 0.95
    if needle in name:
        return 0.9
    if all(word in name for word in needle.split()):
        return 0.85
    words = name.split()
    return max(
        SequenceMatcher(None, needle, name).ratio(),
        *(SequenceMatcher(None, needle, word).ratio() for word in words),
    )


def _folded(*, text: str) -> str:
    return " ".join(text.casefold().split())
