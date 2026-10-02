from collections.abc import Sequence
from typing import Annotated

from pydantic import Field

CategoryName = Annotated[str, Field(min_length=1)]

LIST_CATEGORIES_GUARD = (
    "If this deployment exposes outlook_list_categories, that tool lists the category names of "
    + "the mailbox."
)


def merged_categories(
    current: Sequence[str], *, add: Sequence[str], remove: Sequence[str]
) -> list[str]:
    removed = {name.casefold() for name in remove}
    merged: dict[str, str] = {}
    for name in (*current, *add):
        key = name.casefold()
        if key not in removed and key not in merged:
            merged[key] = name
    return list(merged.values())


def named_in_both(add: Sequence[str], remove: Sequence[str]) -> str | None:
    removed = {name.casefold() for name in remove}
    return next((name for name in add if name.casefold() in removed), None)
