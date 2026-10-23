import asyncio


class AttributionError(Exception):
    """The note does not leave room for the reviewer identity."""


decision_lock = asyncio.Lock()


def reviewer_note(*, note: str, actor: str) -> str:
    """The saved note, with the human reviewer named after the user's text."""
    attributed = f"{note}\nMCP reviewer: {actor}".strip()
    if len(attributed) > 1000:
        raise AttributionError(
            "Shorten the note to leave room for the reviewer attribution (1000 characters total)."
        )
    return attributed
