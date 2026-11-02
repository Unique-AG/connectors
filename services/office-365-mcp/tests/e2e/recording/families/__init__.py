"""Plug-in families of the recorder. Each family module holds plain data. `load` merges them. It
raises `ValueError`, never `assert`, so `python -O` keeps every check."""

import importlib
import pkgutil
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from types import ModuleType
from typing import cast

_WRITE_VERBS = "POST|PUT|PATCH|DELETE"
_NOT_ADDRESSES = ("a@evil.example", "a@thread.evil.example")

type Scrubber = Callable[[Callable[[str], str], str], str]


@dataclass(frozen=True)
class Merged:
    read_tools: frozenset[str]
    read_posts: Mapping[str, tuple[str, ...]]
    read_gets: Mapping[str, tuple[str, ...]]
    write_tools: Mapping[str, tuple[str, ...]]
    external: frozenset[str]
    schema: Mapping[str, str]
    prefixes: tuple[str, ...]
    destinations: frozenset[str]
    forbidden: Mapping[str, frozenset[str]]
    created_only: Mapping[str, int]
    thread_id: tuple[re.Pattern[str], ...]
    bodies: Mapping[str, Scrubber]
    leaks: tuple[re.Pattern[str], ...]
    needs: Mapping[str, str]
    unrecorded: Mapping[str, str]
    probes: Mapping[str, tuple[int, str, int]]
    gaps: Mapping[str, int]


def _union[V](name: str, parts: list[Mapping[str, V]]) -> dict[str, V]:
    merged: dict[str, V] = {}
    for part in parts:
        for key, value in part.items():
            if merged.setdefault(key, value) != value:
                raise ValueError(f"{name}: {key} is claimed twice with different values")
    return merged


def _all(parts: Sequence[frozenset[str]]) -> frozenset[str]:
    return frozenset(one for part in parts for one in part)


def _glob_errors(
    name: str, tools: Mapping[str, tuple[str, ...]], verbs: str = _WRITE_VERBS
) -> list[str]:
    shape = re.compile(rf"(?:{verbs}) /v1\.0/(?!\*(?:/|$))\S+")
    return [
        f"{name} {tool}: {glob} is not a METHOD /v1.0/... glob with a literal first segment"
        for tool, globs in tools.items()
        for glob in globs
        if shape.fullmatch(glob) is None or "**" in glob
    ]


@cache
def load() -> Merged:
    names = sorted(m.name for m in pkgutil.iter_modules(__path__))
    return merge([importlib.import_module(f"{__name__}.{name}") for name in names])


def merge(modules: Sequence[ModuleType]) -> Merged:
    def get[T](attribute: str, empty: T) -> list[T]:
        return [cast("T", getattr(module, attribute, empty)) for module in modules]

    reads = get("READ_TOOLS", frozenset[str]())
    posts = get("READ_POSTS", cast("Mapping[str, tuple[str, ...]]", {}))
    writes = get("WRITE_TOOLS", cast("Mapping[str, tuple[str, ...]]", {}))
    claimed = Counter(tool for part in (*reads, *writes) for tool in part)
    if twice := sorted(tool for tool, count in claimed.items() if count > 1):
        raise ValueError(f"tools claimed twice, or both read and write: {twice}")
    write_tools = _union("WRITE_TOOLS", writes)
    read_posts = _union("READ_POSTS", posts)
    read_gets = _union("READ_GETS", get("READ_GETS", cast("Mapping[str, tuple[str, ...]]", {})))
    if errors := (
        _glob_errors("WRITE_TOOLS", write_tools)
        + _glob_errors("READ_POSTS", read_posts)
        + _glob_errors("READ_GETS", read_gets, "GET")
    ):
        raise ValueError("; ".join(errors))
    prefixes = tuple(p for part in get("PREFIXES", cast("tuple[str, ...]", ())) for p in part)
    if bad := [p for p in prefixes if not p.endswith("/")]:
        raise ValueError(f"PREFIXES must end in a slash: {bad}")
    gaps = {
        tool: seconds
        for seconds, read, write in zip(get("GAP_SECONDS", 0), reads, writes, strict=True)
        if seconds
        for tool in (*read, *write)
    }
    thread_id = tuple(
        p for part in get("THREAD_ID", cast("tuple[re.Pattern[str], ...]", ())) for p in part
    )
    if bad := [p.pattern for p in thread_id if _broad(p)]:
        raise ValueError(f"THREAD_ID must hold whole-token Teams id shapes: {bad}")
    return Merged(
        _all(reads),
        read_posts,
        read_gets,
        write_tools,
        _all(get("EXTERNAL", frozenset[str]())),
        _union("SCHEMA", get("SCHEMA", cast("Mapping[str, str]", {}))),
        prefixes,
        _all(get("DESTINATIONS", frozenset[str]())),
        _union("FORBIDDEN", get("FORBIDDEN", cast("Mapping[str, frozenset[str]]", {}))),
        _union("CREATED_ONLY", get("CREATED_ONLY", cast("Mapping[str, int]", {}))),
        thread_id,
        _union("BODIES", get("BODIES", cast("Mapping[str, Scrubber]", {}))),
        tuple(p for part in get("LEAKS", cast("tuple[re.Pattern[str], ...]", ())) for p in part),
        _union("NEEDS", get("NEEDS", cast("Mapping[str, str]", {}))),
        _union("UNRECORDED", get("UNRECORDED", cast("Mapping[str, str]", {}))),
        _union("PROBES", get("PROBES", cast("Mapping[str, tuple[int, str, int]]", {}))),
        gaps,
    )


def _broad(pattern: re.Pattern[str]) -> bool:
    anchored = re.search(r"@thread|@unq|spaces$", pattern.pattern) is not None
    return not anchored or any(pattern.fullmatch(one) for one in _NOT_ADDRESSES)
