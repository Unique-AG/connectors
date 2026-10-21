"""`upstream/`: the client of the system the MCP fronts, one layer folder per kind."""

import shutil
from pathlib import Path

from mcp_scaffold.options import Options
from mcp_scaffold.skeleton import LAYERS, PACKAGE, copy_root_files


def write_upstream(options: Options, target: Path) -> None:
    """Without an upstream, the skeleton's empty `upstream/` stays, as the layers contract needs."""
    if options.upstream is None:
        return
    layer = target / "src" / PACKAGE / "upstream"
    shutil.copytree(LAYERS / "upstream" / options.upstream, layer, dirs_exist_ok=True)
    shutil.copy(LAYERS / "upstream" / "settings.py", layer / "settings.py")
    copy_root_files(options.upstream, target)
