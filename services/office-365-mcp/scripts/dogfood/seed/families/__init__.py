"""Seed plug-ins, one module per family. A family module exports `PHASES`, `steps(ctx, owner,
phases)` and `sweep(graph, owner)`, which yields the (method, path) or the (method, path, body)
of every item that holds "seed-v1 case-" in its name. It may export `cleanup(graph, ctx, owner,
phases)`, which yields the same tuples for the items that the given phases of the family
created. `cleanup --phases` runs it. It may export `OPT_IN`, the phases that `plan` and `apply`
skip unless `--phases` names them."""

import importlib
import pkgutil
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, Protocol, cast

from model import Context, Step

if TYPE_CHECKING:
    from seed import Graph


class Family(Protocol):
    PHASES: tuple[str, ...]
    steps: Callable[[Context, str, set[str]], list[Step]]
    sweep: Callable[[Graph, str], Iterator[tuple[str, str] | tuple[str, str, Any]]]


def load() -> tuple[Family, ...]:
    names = sorted(found.name for found in pkgutil.iter_modules(__path__))
    return tuple(cast("Family", importlib.import_module(f"{__name__}.{name}")) for name in names)
