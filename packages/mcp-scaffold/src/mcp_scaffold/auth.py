"""`--auth credentials`: the sign-in, written into the layers it touches. The MCP owns the code,
as it owns the rest of what the scaffold writes."""

import shutil
from pathlib import Path

from mcp_scaffold.options import Options
from mcp_scaffold.skeleton import LAYERS, PACKAGE, copy_root_files


def write_auth(options: Options, target: Path) -> None:
    if options.auth is None:
        return
    package = target / "src" / PACKAGE
    for layer in ["mcp", "persistence", "shared", "upstream"]:
        shutil.copytree(LAYERS / "auth" / layer, package / layer, dirs_exist_ok=True)
    copy_root_files("auth", target)
