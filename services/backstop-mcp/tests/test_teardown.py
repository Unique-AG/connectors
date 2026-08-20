"""`close_singletons` releases and drops every cached provider.

Adding an `@lru_cache(maxsize=1)` provider is two edits — the provider, and its entry in
`teardown.PROVIDERS`. Forgetting the second leaks a stale singleton into the next `create_app`
and, because the suite's autouse teardown is this same function, into the next test: a config
read before a `monkeypatch.setenv`, or an httpx pool bound to a dead event loop. The coverage
test below is what makes the missing edit fail the suite rather than surface as an
order-dependent flake somewhere else — the same gap rule 7 in `test_layering.py` closes for
tools.
"""

import importlib
import pathlib
from typing import Protocol, cast, runtime_checkable

from backstop_mcp import dependencies
from backstop_mcp.teardown import PROVIDERS, close_singletons

_SRC = pathlib.Path(__file__).parent.parent / "src" / "backstop_mcp"


@runtime_checkable
class _Cached(Protocol):
    """Structurally an `lru_cache` wrapper — what a provider is, and `PROVIDERS` a tuple of."""

    def cache_clear(self) -> None: ...
    def cache_info(self) -> object: ...


def _name(provider: object) -> str:
    name = getattr(provider, "__name__", None)
    assert isinstance(name, str), f"expected a named provider, got {provider!r}"
    return name


def _provider_modules() -> list[str]:
    """The root providers module and every feature-owned one, by import path."""
    feature_modules = [
        f"backstop_mcp.features.{path.parent.name}.dependencies"
        for path in sorted((_SRC / "features").glob("*/dependencies.py"))
    ]
    return ["backstop_mcp.dependencies", *feature_modules]


def _cached_provider_names(module_name: str) -> set[str]:
    """Names a provider module defines that are cached — not ones it merely imports."""
    members = cast("dict[str, object]", vars(importlib.import_module(module_name)))
    return {
        name
        for name, value in members.items()
        if isinstance(value, _Cached) and getattr(value, "__module__", None) == module_name
    }


def test_the_provider_modules_are_actually_there() -> None:
    """Guards the guard: a moved tree must not make the coverage assertion vacuous."""
    modules = _provider_modules()

    assert len(modules) > 1, "no feature dependencies modules found — has the tree moved?"
    assert all(_cached_provider_names(module) for module in modules)


def test_every_cached_provider_is_torn_down() -> None:
    declared = {_name(provider) for provider in PROVIDERS}
    defined = {name for module in _provider_modules() for name in _cached_provider_names(module)}

    assert defined - declared == set(), (
        "a cached provider is missing from teardown.PROVIDERS, so its singleton would survive "
        "close_singletons() into the next create_app"
    )
    assert declared - defined == set(), (
        "teardown.PROVIDERS names something that is no longer a cached provider"
    )


async def test_close_singletons_drops_a_primed_provider() -> None:
    """Behavioural: prime one, tear down, and the next read is a fresh construction."""
    _ = dependencies.get_backstop_config()
    assert dependencies.get_backstop_config.cache_info().currsize == 1

    await close_singletons()

    assert dependencies.get_backstop_config.cache_info().currsize == 0


async def test_close_singletons_is_safe_when_nothing_was_built() -> None:
    """The autouse fixture runs after every test, including ones that touched no provider.

    Building an engine here just to dispose it would read a `DB_URL` such a test never set.
    """
    await close_singletons()

    assert dependencies.get_engine.cache_info().currsize == 0
    assert dependencies.get_backstop_client_factory.cache_info().currsize == 0
