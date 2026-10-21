"""The versions a generated MCP pins: the scaffold's `service*` dependency groups for what comes
from PyPI, and each shared package's own version for what comes from `packages/`."""

import re
import tomllib
from pathlib import Path
from typing import cast

_SCAFFOLD = cast(
    dict[str, dict[str, object]],
    tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text()),
)


def scaffold_version() -> str:
    """The version every file of a generated MCP is stamped with."""
    return cast(str, _SCAFFOLD["project"]["version"])


def pinned(group: str) -> list[str]:
    return cast(list[str], _SCAFFOLD["dependency-groups"][group])


def dependency_names() -> set[str]:
    """Every distribution a generated MCP can depend on from PyPI."""
    return {
        re.split(r"[\[=<>]", pin, maxsplit=1)[0]
        for group in _SCAFFOLD["dependency-groups"]
        if group.startswith("service")
        for pin in pinned(group)
    }


def shared(repo: Path, name: str, extra: str = "") -> str:
    project = cast(
        dict[str, dict[str, object]],
        tomllib.loads((repo / "packages" / name / "pyproject.toml").read_text()),
    )["project"]
    return f"{name}{extra}=={project['version']}"


def source(name: str) -> str:
    return f'{name} = {{ path = "../../packages/{name}" }}'
