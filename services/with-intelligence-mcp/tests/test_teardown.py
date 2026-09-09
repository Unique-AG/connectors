"""`close_singletons` releases and drops every cached provider.

Adding a provider is two edits — the provider, and its entry in `PROVIDERS`. Forgetting the
second leaks a stale singleton into the next `create_app` and, since the suite's autouse
teardown is this same function, into the next test.
"""

import importlib
import pathlib
from typing import Protocol, cast, runtime_checkable

import pytest

from with_intelligence_mcp import dependencies
from with_intelligence_mcp.teardown import PROVIDERS, close_singletons

_SRC = pathlib.Path(__file__).parent.parent / "src" / "with_intelligence_mcp"


@runtime_checkable
class _Cached(Protocol):
    """Structurally an `lru_cache` wrapper."""

    def cache_clear(self) -> None: ...
    def cache_info(self) -> object: ...


def _name(provider: object) -> str:
    name = getattr(provider, "__name__", None)
    assert isinstance(name, str), f"expected a named provider, got {provider!r}"
    return name


def _provider_modules() -> list[str]:
    feature_modules = [
        f"with_intelligence_mcp.features.{path.parent.name}.dependencies"
        for path in sorted((_SRC / "features").glob("*/dependencies.py"))
    ]
    return ["with_intelligence_mcp.dependencies", *feature_modules]


def _cached_provider_names(module_name: str) -> set[str]:
    """Cached providers a module defines — not ones it merely imports."""
    module = importlib.import_module(module_name)
    members = cast("dict[str, object]", vars(module))
    return {
        name
        for name, value in members.items()
        if isinstance(value, _Cached) and getattr(value, "__module__", None) == module_name
    }


class TestProvidersCoversEveryCachedProvider:
    def test_every_cached_provider_is_listed(self) -> None:
        listed = {_name(provider) for provider in PROVIDERS}
        defined: set[str] = set()
        for module_name in _provider_modules():
            defined |= _cached_provider_names(module_name)
        missing = defined - listed
        assert missing == set(), "cached providers missing from teardown.PROVIDERS: " + ", ".join(
            sorted(missing)
        )

    def test_nothing_listed_has_gone_away(self) -> None:
        defined: set[str] = set()
        for module_name in _provider_modules():
            defined |= _cached_provider_names(module_name)
        stale = {_name(provider) for provider in PROVIDERS} - defined
        assert stale == set(), (
            "teardown.PROVIDERS lists providers that no longer exist: " + ", ".join(sorted(stale))
        )

    def test_the_detection_finds_a_known_provider(self) -> None:
        """Guards the coverage tests above from passing because they found nothing."""
        assert "get_app_config" in _cached_provider_names("with_intelligence_mcp.dependencies")


class TestCloseSingletons:
    async def test_drops_a_cached_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`AppConfig` refuses the default issuer in production, hence `APP_ENV`."""
        monkeypatch.setenv("APP_ENV", "development")
        first = dependencies.get_app_config()
        assert dependencies.get_app_config() is first
        await close_singletons()
        assert dependencies.get_app_config() is not first

    async def test_is_safe_when_nothing_was_ever_built(self) -> None:
        await close_singletons()
        await close_singletons()
