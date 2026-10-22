"""`mcp-architecture-imports`: import-linter on the MCP in the current folder, first with the
contracts every MCP keeps, rendered by `render_importlinter` so nothing in the MCP changes them,
then with the MCP's own contracts in its `[tool.importlinter]`."""

import sys
import tempfile
import tomllib
from pathlib import Path
from typing import cast

from importlinter.cli import lint_imports

from mcp_architecture.contracts import render_importlinter


def main() -> None:
    sys.exit(check_imports(Path.cwd()))


def check_imports(root: Path) -> int:
    """1 when a contract every MCP keeps or one of the MCP's own is broken, else 0."""
    pyproject = cast(
        dict[str, dict[str, object]], tomllib.loads((root / "pyproject.toml").read_text())
    )
    package = str(pyproject["project"]["name"]).replace("-", "_")
    cache = str(root / ".import_linter_cache")
    with tempfile.TemporaryDirectory() as folder:
        shared = Path(folder) / "importlinter.toml"
        shared.write_text(render_importlinter(package))
        status = lint_imports(config_filename=str(shared), cache_dir=cache, no_logo=True)
    if "importlinter" in pyproject.get("tool", {}):
        status |= lint_imports(
            config_filename=str(root / "pyproject.toml"), cache_dir=cache, no_logo=True
        )
    return status
