"""The repository files a new service registers in: commit scope, workspace and release."""

import json
import re
import textwrap
from pathlib import Path
from typing import cast

from mcp_scaffold.options import Options


def register(options: Options, repo: Path, *, release: bool) -> None:
    """Commit scope, release, and the pnpm workspace exclusion every Python service has.

    Each entry is added once, so a name registered before, by a service since removed and
    generated again, is not listed twice.
    """
    name = options.name

    gitcommitizen = repo / ".gitcommitizen"
    text = gitcommitizen.read_text()
    assert "# Services\n" in text, ".gitcommitizen has no '# Services' section"
    scope = f"{name} = services/{name}/**\n"
    if scope not in text:
        gitcommitizen.write_text(text.replace("# Services\n", f"# Services\n{scope}", 1))

    workspace = repo / "pnpm-workspace.yaml"
    text = workspace.read_text()
    exclusions: list[str] = re.findall(r'^  - "!services/.+"\n', text, flags=re.MULTILINE)
    assert exclusions, "pnpm-workspace.yaml excludes no Python service"
    exclusion = f'  - "!services/{name}"\n'
    if exclusion not in exclusions:
        last = exclusions[-1]
        workspace.write_text(text.replace(last, f"{last}{exclusion}", 1))

    if release:
        _register_release(name, repo)


def _register_release(name: str, repo: Path) -> None:
    chart = f"deploy/helm-charts/{name}"
    package = {
        "release-type": "python",
        "component": name,
        "extra-files": [
            {"type": "yaml", "path": f"{chart}/Chart.yaml", "jsonpath": "$.version"},
            {"type": "yaml", "path": f"{chart}/Chart.yaml", "jsonpath": "$.appVersion"},
            {"type": "generic", "path": f"{chart}/values.yaml"},
            {
                "type": "toml",
                "path": "uv.lock",
                "jsonpath": "$.package[?(@.source.editable)].version",
            },
        ],
    }
    config = repo / "release-please-config.json"
    text = config.read_text()
    packages = cast(dict[str, dict[str, object]], json.loads(text))["packages"]
    if f"services/{name}" not in packages:
        closing = "    }\n  }\n}\n"
        assert text.endswith(closing), (
            "release-please-config.json does not end with the packages map"
        )
        entry = textwrap.indent(f'"services/{name}": {json.dumps(package, indent=2)}', "    ")
        config.write_text(f"{text[: -len(closing)]}    }},\n{entry}\n  }}\n}}\n")

    manifest = repo / ".release-please-manifest.json"
    versions = cast(dict[str, str], json.loads(manifest.read_text()))
    versions.setdefault(f"services/{name}", "0.0.1")
    manifest.write_text(json.dumps(versions, indent=2) + "\n")

    rerun = repo / ".github" / "workflows" / "release-rerun.yaml"
    text = rerun.read_text()
    block = re.search(r"(        options:\n)((?:          - .+\n)+)", text)
    assert block, "release-rerun.yaml has no service options list"
    services = sorted({*re.findall(r"- (.+)", block.group(2)), name})
    listed = "".join(f"          - {service}\n" for service in services)
    rerun.write_text(text[: block.start(2)] + listed + text[block.end(2) :])
