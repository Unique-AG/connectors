import tomllib
from pathlib import Path
from typing import cast


class Service:
    """A scaffolded MCP: its folder, and the package its import contracts are rooted at."""

    def __init__(self, root: Path) -> None:
        tool = _tool(root / "pyproject.toml")
        self.root: Path = root
        self.pyproject: Path = root / "pyproject.toml"
        self.package: str = _root_package(tool, self.pyproject)
        self.source: Path = root / "src" / self.package
        self.contexts: Path = self.source / "contexts"
        self.tools: Path = self.source / "mcp" / "tools"
        self.generated: list[Path] = _generated(tool, root)
        self.type_check: dict[str, object] = tool.get("basedpyright", {})


def _tool(pyproject: Path) -> dict[str, dict[str, object]]:
    return cast(dict[str, dict[str, object]], tomllib.loads(pyproject.read_text()).get("tool", {}))


def _root_package(tool: dict[str, dict[str, object]], pyproject: Path) -> str:
    package = tool.get("importlinter", {}).get("root_package")
    assert isinstance(package, str), f"{pyproject} has no [tool.importlinter] root_package"
    return package


def _generated(tool: dict[str, dict[str, object]], root: Path) -> list[Path]:
    """What mcp-openapi's codegen writes from the vendor's spec, with the vendor's names."""
    codegen = tool.get("mcp-openapi", {})
    return [
        root / str(codegen[key]) for key in ("models-output", "operations-output") if key in codegen
    ]
