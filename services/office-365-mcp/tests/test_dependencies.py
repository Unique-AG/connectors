"""The declarations that keep two directly-imported packages from being dropped as redundant.

`starlette` also reaches this service through `fastmcp`, and `unique_toolkit` through `unique-mcp`,
so the declaration reads like duplication until an upstream package drops its own edge and the
import breaks at runtime instead of at resolve time.
"""

import ast
import pathlib
import re
import tomllib
from typing import cast

_SERVICE_ROOT = pathlib.Path(__file__).parent.parent
_SRC = _SERVICE_ROOT / "src" / "office_365_mcp"

# `unique-toolkit[monitoring,otel]==2026.34.0.dev7` → name, extras, version.
_REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)(?:\[(?P<extras>[^]]*)\])?")


def _declared_dependencies() -> dict[str, set[str]]:
    pyproject = tomllib.loads((_SERVICE_ROOT / "pyproject.toml").read_text())
    project = cast("dict[str, object]", pyproject["project"])
    requirements = project["dependencies"]
    assert isinstance(requirements, list), "[project].dependencies is not an array"
    declared: dict[str, set[str]] = {}
    for requirement in cast("list[str]", requirements):
        match = _REQUIREMENT.match(requirement)
        assert match is not None, f"unparseable requirement: {requirement}"
        name = match.group("name").lower().replace("_", "-")
        extras = match.group("extras") or ""
        declared[name] = {extra.strip() for extra in extras.split(",") if extra.strip()}
    return declared


def _imported_modules(source: pathlib.Path) -> set[str]:
    tree = ast.parse(source.read_text(), filename=str(source))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            modules.add(node.module)
    return modules


class TestStarlette:
    def test_the_app_imports_starlette_directly(self) -> None:
        """Guards the guard: without these imports the declaration below has no justification."""
        modules = _imported_modules(_SRC / "app.py")
        assert {
            "starlette.applications",
            "starlette.middleware",
            "starlette.requests",
            "starlette.responses",
        } <= modules

    def test_starlette_is_a_declared_dependency(self) -> None:
        assert "starlette" in _declared_dependencies(), (
            "app.py imports starlette directly, so it must be declared — it arrives via fastmcp "
            + "today, which is exactly why relying on that is a silent break waiting to happen."
        )


class TestUniqueToolkit:
    def test_metrics_imports_the_toolkit_registry_directly(self) -> None:
        assert "unique_toolkit.monitoring" in _imported_modules(_SRC / "metrics.py")

    def test_unique_toolkit_is_declared_with_the_monitoring_extra(self) -> None:
        declared = _declared_dependencies()
        assert "unique-toolkit" in declared, (
            "metrics.py imports unique_toolkit.monitoring directly, so it must be declared — it "
            + "arrives via unique-mcp today, and that edge is not ours to depend on."
        )
        assert "monitoring" in declared["unique-toolkit"], (
            "the monitoring extra is what installs prometheus-client, which is the package "
            + "unique_toolkit.monitoring.REGISTRY is a registry of."
        )
