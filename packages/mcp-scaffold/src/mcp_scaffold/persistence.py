"""`persistence/`: each store's files side by side, and the templates of the `Persistence` that
holds them."""

import shutil
from pathlib import Path

from mcp_scaffold.options import Options
from mcp_scaffold.skeleton import LAYERS, PACKAGE, copy_root_files


def write_persistence(options: Options, target: Path) -> None:
    if not options.opens_persistence:
        return
    layer = target / "src" / PACKAGE / "persistence"
    for store in options.stores:
        shutil.copytree(LAYERS / "persistence" / store, layer, dirs_exist_ok=True)
        copy_root_files(store, target)
    for template in ["__init__.py.jinja", "persistence.py.jinja"]:
        shutil.copy(LAYERS / "persistence" / template, layer / template)
