from collections.abc import Iterator

from model import Context, Step

PHASES: tuple[str, ...] = ()


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    return []


def sweep(graph: object, owner: str) -> Iterator[tuple[str, str]]:
    return iter(())
