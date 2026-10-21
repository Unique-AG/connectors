"""The settings an MCP reads from its environment, which may hold its secrets."""

import importlib
from collections.abc import Iterator

from pydantic_settings import BaseSettings


def settings_showing_input_in_errors(package: str) -> list[str]:
    """Each settings class of `package` whose validation error would print the value it was given,
    such as an API key from the environment. `mcp_configs.shared_config` hides it.

    `main` builds every settings class the MCP has, so importing it loads them all.
    """
    importlib.import_module(f"{package}.main")
    return sorted(
        f"{settings.__module__}.{settings.__qualname__}"
        for settings in _subclasses(BaseSettings)
        if settings.__module__.partition(".")[0] == package
        and not settings.model_config.get("hide_input_in_errors")
    )


def _subclasses(cls: type[BaseSettings]) -> Iterator[type[BaseSettings]]:
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _subclasses(subclass)
