"""The repository files a new service registers in: workspace and release."""

import json
import re
import textwrap
from pathlib import Path
from typing import cast

from mcp_scaffold.options import Options
from mcp_scaffold.pins import dependency_names


def name_conflict(name: str, repo: Path) -> str | None:
    """Why `name` cannot be a new service in `repo`, or None when it can.

    A release entry that a removed service left blocks the name: its version would carry on from
    the removed service's.
    """
    service = f"services/{name}"
    if (repo / service).exists():
        return (
            f"{service} already exists. If git lists nothing there, it is what a failed run "
            f"left, which `git clean -fdx {service}` removes"
        )
    if name in dependency_names() or (repo / "packages" / name).exists():
        return f"{name} would shadow the package of that name"
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
    """Release, and the pnpm workspace exclusion every Python service has.

    An exclusion that a service since removed left under the same name is not listed twice.
    `name_conflict` has refused a name with a release entry left.
    """
    name = options.name

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

    for workflow in _RELEASE_WORKFLOWS:
        _add_service_option(name, repo / ".github" / "workflows" / workflow)


def _add_service_option(name: str, workflow: Path) -> None:
    """Lists `name` among the services the workflow's form offers, kept sorted."""
    text = workflow.read_text()
    block = re.search(r"(        options:\n)((?:          - .+\n)+)", text)
    assert block, f"{workflow.name} has no service options list"
    services = sorted({*re.findall(r"- (.+)", block.group(2)), name})
    listed = "".join(f"          - {service}\n" for service in services)
    workflow.write_text(text[: block.start(2)] + listed + text[block.end(2) :])


_RELEASE_CONFIG = "release-please-config.json"
_RELEASE_MANIFEST = ".release-please-manifest.json"
# The workflows a service is started from by hand: a dev build, and re-running a release.
_RELEASE_WORKFLOWS = ("release-dev.yaml", "release-rerun.yaml")
