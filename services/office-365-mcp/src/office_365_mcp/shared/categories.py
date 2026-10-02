from collections.abc import Sequence

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
