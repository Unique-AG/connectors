"""`pyproject.toml`: the description, the dependencies the choices bring and the import
contracts."""

import json
import re
from pathlib import Path

from mcp_architecture import render_importlinter

from mcp_scaffold.options import Options, Persistence, Upstream
from mcp_scaffold.pins import pinned, shared, source
from mcp_scaffold.skeleton import PACKAGE


def edit_pyproject(options: Options, target: Path, repo: Path) -> None:
    pyproject = target / "pyproject.toml"
    text = pyproject.read_text()
    text = re.sub(
        r'^description = ".*"$',
        f"description = {json.dumps(options.description)}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    openapi = options.upstream is Upstream.OPENAPI
    dependencies = [
        *pinned("service"),
        shared(repo, "mcp-runtime"),
        *([shared(repo, "mcp-openapi"), *pinned("service-openapi")] if openapi else []),
        *(dependency for store in options.stores for dependency in pinned(f"service-{store}")),
    ]
    dev = [
        *pinned("service-dev"),
        shared(repo, "mcp-architecture"),
        *([shared(repo, "mcp-openapi", "[codegen]")] if openapi else []),
        *(pinned("service-postgres-dev") if Persistence.POSTGRES in options.persistence else []),
    ]
    packages = ["mcp-architecture", *(["mcp-openapi"] if openapi else []), "mcp-runtime"]
    for old, new in [
        ("dependencies = []\n", dependency_array("dependencies", dependencies)),
        ("dev = []\n", dependency_array("dev", dev)),
        (
            "[tool.uv.sources]\n",
            "[tool.uv.sources]\n" + "".join(f"{source(p)}\n" for p in packages),
        ),
        ("[tool.importlinter]\n", render_importlinter(PACKAGE)),
    ]:
        assert old in text, f"the skeleton's pyproject.toml no longer has {old!r}"
        text = text.replace(old, new, 1)
    if not openapi:
        text = re.sub(r"\n\[tool\.mcp-openapi\]\n(?:[^\n]+\n)*", "", text)
        text = re.sub(r"\n\[tool\.ruff\.lint\.per-file-ignores\]\n(?:[^\n]+\n)*", "", text)
    pyproject.write_text(text)


def dependency_array(key: str, dependencies: list[str]) -> str:
    listed = "".join(f"    {json.dumps(dependency)},\n" for dependency in sorted(dependencies))
    return f"{key} = [\n{listed}]\n"
