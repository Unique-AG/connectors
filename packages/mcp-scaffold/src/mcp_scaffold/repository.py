"""The repository files a new service registers in: commit scope, workspace and release."""

import json
import re
import textwrap
from pathlib import Path
from typing import cast

from mcp_scaffold.options import Options
from mcp_scaffold.pins import dependency_names


def name_conflict(name: str, repo: Path) -> str | None:
    """Why `name` cannot be a new service in `repo`, or None when it can.

    A scope that a service since removed left under the same name may be registered again, but
    not a release: its version would carry on from the removed service's.
    """
    service = f"services/{name}"
    if (repo / service).exists():
        return (
            f"{service} already exists. If git lists nothing there, it is what a failed run "
            f"left, which `git clean -fdx {service}` removes"
        )
    if name in dependency_names() or (repo / "packages" / name).exists():
        return f"{name} would shadow the package of that name"
    scopes = (repo / ".gitcommitizen").read_text()
    scope = re.search(rf"^{re.escape(name)} = (.+)$", scopes, flags=re.MULTILINE)
    if scope is not None and scope.group(1) != f"{service}/**":
        return f"{name} is already the commit scope of {scope.group(1)}"
    config = cast(dict[str, dict[str, object]], json.loads((repo / _RELEASE_CONFIG).read_text()))
    manifest = cast(dict[str, str], json.loads((repo / _RELEASE_MANIFEST).read_text()))
    releases = [
        file
        for file, entries in [(_RELEASE_CONFIG, config["packages"]), (_RELEASE_MANIFEST, manifest)]
        if service in entries
    ]
    if releases:
        return (
            f"{service} still has a release entry in {' and '.join(releases)}, from a service "
            "since removed. Remove it, or pick another name"
        )
    return None


def register(options: Options, repo: Path, *, release: bool) -> None:
    """Commit scope, release, and the pnpm workspace exclusion every Python service has.

    A scope and an exclusion that a service since removed left under the same name are not
    listed twice. `name_conflict` has refused a name with a release entry left.
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
    config = repo / _RELEASE_CONFIG
    text = config.read_text()
    closing = "    }\n  }\n}\n"
    assert text.endswith(closing), "release-please-config.json does not end with the packages map"
    entry = textwrap.indent(f'"services/{name}": {json.dumps(package, indent=2)}', "    ")
    config.write_text(f"{text[: -len(closing)]}    }},\n{entry}\n  }}\n}}\n")

    manifest = repo / _RELEASE_MANIFEST
    versions = cast(dict[str, str], json.loads(manifest.read_text()))
    versions[f"services/{name}"] = "0.0.0"
    manifest.write_text(json.dumps(versions, indent=2) + "\n")

    rerun = repo / ".github" / "workflows" / "release-rerun.yaml"
    text = rerun.read_text()
    block = re.search(r"(        options:\n)((?:          - .+\n)+)", text)
    assert block, "release-rerun.yaml has no service options list"
    services = sorted({*re.findall(r"- (.+)", block.group(2)), name})
    listed = "".join(f"          - {service}\n" for service in services)
    rerun.write_text(text[: block.start(2)] + listed + text[block.end(2) :])


_RELEASE_CONFIG = "release-please-config.json"
_RELEASE_MANIFEST = ".release-please-manifest.json"
