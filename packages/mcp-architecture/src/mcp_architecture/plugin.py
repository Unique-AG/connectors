"""A pytest plugin: in an MCP that declares `[tool.importlinter]`, `service_tests` joins the MCP's
`tests/` package, beside its conftest, so the MCP keeps no copy of the checks it could loosen."""

import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import cast, override

import pytest

from mcp_architecture import service_tests

# Not a file: the module's tests run under this name, as `tests/mcp_architecture.py::test_...`.
_MODULE = "mcp_architecture.py"


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
    if not pyproject.is_file():
        return False
    tool = cast(dict[str, object], tomllib.loads(pyproject.read_text()).get("tool", {}))
    return "importlinter" in tool
