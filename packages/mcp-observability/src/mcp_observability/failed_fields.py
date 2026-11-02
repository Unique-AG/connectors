"""Which fields a pydantic validation failed on: the path and the type of the input, never the
input itself."""

from collections import deque
from collections.abc import Collection
from collections.abc import Iterable
from typing import cast

from pydantic import ValidationError

# How many a log line or an error message lists. One broken field fails once per record, so a
# page of thousands of records would otherwise make a line too long to ship or read.
FAILED_FIELDS_SHOWN = 10
# How deep a container input's type is described: `list[dict[str, int]]`, not every level.
_TYPE_DEPTH = 2


def failed_fields(failures: Iterable[BaseException]) -> list[str]:
    """`path (error type, got input type)` for each pydantic error in `failures` or what they were
    raised from, once each, in pydantic's order. A container shows its types: `list[int | str]`."""
    entries = [
        _entry(error["loc"], error["type"], cast("object", error.get("input")))
        for failure in _with_causes(failures)
        if isinstance(failure, ValidationError)
        for error in failure.errors(include_url=False, include_context=False)
    ]
    return list(dict.fromkeys(entries))


def _entry(loc: tuple[int | str, ...], error_type: str, value: object) -> str:
    path = ".".join(str(part) for part in loc) or "<root>"
    # A missing field's input is the object it is missing from, which says nothing about it.
    if error_type == "missing":
        return f"{path} ({error_type})"
    return f"{path} ({error_type}, got {_type_of(value, _TYPE_DEPTH)})"


def _type_of(value: object, depth: int) -> str:
    if value is None:
        return "None"
    if depth == 0:
        return type(value).__name__
    if isinstance(value, tuple):
        items = cast("tuple[object, ...]", value)
        return f"tuple({', '.join(_type_of(item, depth - 1) for item in items)})"
    if isinstance(value, dict):
        entries = cast("dict[object, object]", value)
        if not entries:
            return "dict"
        return f"dict[{_union(entries.keys(), depth)}, {_union(entries.values(), depth)}]"
    if isinstance(value, list | set | frozenset):
        members = cast("Collection[object]", value)
        name = type(members).__name__
        return f"{name}[{_union(members, depth)}]" if members else name
    return type(value).__name__


def _union(items: Iterable[object], depth: int) -> str:
    return " | ".join(sorted({_type_of(item, depth - 1) for item in items}))


def _with_causes(failures: Iterable[BaseException]) -> list[BaseException]:
    """`__context__` too: `raise ... from None` hides it from a traceback but still sets it."""
    pending = deque(failures)
    seen: dict[int, BaseException] = {}
    while pending:
        current = pending.popleft()
        if id(current) in seen:
            continue
        seen[id(current)] = current
        pending.extend(
            linked for linked in (current.__cause__, current.__context__) if linked is not None
        )
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
    return list(seen.values())
