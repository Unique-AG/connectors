from collections.abc import Iterable

__all__ = ["first_item"]


def first_item[T](items: Iterable[T]) -> T | None:
    """The first element of `items`, or None when there is none.

    Takes an `Iterable` rather than a `Sequence` so a generator expression works alongside the
    lists and tuples — the caller filtering as it goes is the common case.
    """
    return next(iter(items), None)
