"""A pytest plugin: in an MCP that declares `[tool.importlinter]`, `service_tests` joins the MCP's
`tests/` package, beside its conftest, so the MCP keeps no copy of the checks it could loosen."""

import re
import tomllib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import cast, override

import pytest

from mcp_architecture import service_tests

# Not a file: the module's tests run under this name, as `tests/mcp_architecture.py::test_...`.
_MODULE = "mcp_architecture.py"
# A requirement's name, normalized as PEP 503 does, matches `mcp-architecture`.
_ARCHITECTURE_REQUIREMENT = re.compile(r"mcp[-_.]+architecture(?![\w.-])", re.IGNORECASE)


def pytest_configure(config: pytest.Config) -> None:
    """A service, unlike a package such as mcp-scaffold that uses mcp-architecture's API, has a
    `contexts` folder, so removing `[tool.importlinter]` cannot skip its checks."""
    root = config.rootpath
    pyproject = root / "pyproject.toml"
    is_service = any(path.is_dir() for path in root.glob("src/*/contexts"))
    if (
        is_service
        and _depends_on_the_architecture(pyproject)
        and not _declares_contracts(pyproject)
    ):
        raise pytest.UsageError(
            f"{pyproject} depends on mcp-architecture but has no [tool.importlinter], so its "
            "architecture would go unchecked. Restore the table the scaffold wrote."
        )


@pytest.hookimpl(tryfirst=True)
def pytest_collect_directory(path: Path, parent: pytest.Collector) -> pytest.Collector | None:
    root = parent.config.rootpath
    if path != root / "tests" or not _declares_contracts(root / "pyproject.toml"):
        return None
    assert (path / "__init__.py").is_file(), (
        f"{path} needs an __init__.py for the checks to join it"
    )
    # pytest types `parent` as unknown.
    return _ServiceTests.from_parent(parent, path=path)  # pyright: ignore[reportUnknownMemberType]


class _ServiceTests(pytest.Package):
    @override
    def collect(self) -> Iterable[pytest.Item | pytest.Collector]:
        yield from super().collect()
        module = pytest.Module.from_parent(self, path=self.path / _MODULE)  # pyright: ignore[reportUnknownMemberType]
        module.obj = service_tests
        yield module


def _declares_contracts(pyproject: Path) -> bool:
    return "importlinter" in cast(dict[str, object], _read(pyproject).get("tool", {}))


def _depends_on_the_architecture(pyproject: Path) -> bool:
    return any(
        _ARCHITECTURE_REQUIREMENT.match(requirement.strip())
        for requirement in _requirements(_read(pyproject))
    )


def _requirements(table: dict[str, object]) -> Iterator[str]:
    project = cast(dict[str, object], table.get("project", {}))
    optional = cast(dict[str, list[str]], project.get("optional-dependencies", {}))
    groups = cast(dict[str, list[object]], table.get("dependency-groups", {}))
    yield from cast(list[str], project.get("dependencies", []))
    for requirements in [*optional.values(), *groups.values()]:
        # A dependency group may also hold an `{include-group = ...}` table.
        yield from (requirement for requirement in requirements if isinstance(requirement, str))


def _read(pyproject: Path) -> dict[str, object]:
    return tomllib.loads(pyproject.read_text()) if pyproject.is_file() else {}
