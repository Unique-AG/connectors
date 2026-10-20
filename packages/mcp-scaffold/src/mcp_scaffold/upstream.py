"""`upstream/`: the client of the system the MCP fronts, one layer folder per kind."""

import shutil
from pathlib import Path

from mcp_scaffold.options import Options
from mcp_scaffold.skeleton import LAYERS, PACKAGE, copy_root_files


def write_upstream(options: Options, target: Path) -> None:
    layer = target / "src" / PACKAGE / "upstream"
    shutil.copytree(LAYERS / "upstream" / options.upstream, layer)
    if options.opens_upstream:
        shutil.copy(LAYERS / "upstream" / "settings.py", layer / "settings.py")
    copy_root_files(options.upstream, target)
