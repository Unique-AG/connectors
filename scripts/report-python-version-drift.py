"""Report the PyPI packages two projects' locks resolve to different versions; never fails."""

import os
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

root = Path(__file__).resolve().parent.parent
projects_by_version: defaultdict[str, defaultdict[str, list[str]]] = defaultdict(
    lambda: defaultdict(list)
)
for lock in sorted([*root.glob("packages/*/uv.lock"), *root.glob("services/*/uv.lock")]):
    for package in tomllib.loads(lock.read_text())["package"]:
        if "registry" in package.get("source", {}):
            projects_by_version[package["name"]][package["version"]].append(lock.parent.name)

drift = {name: versions for name, versions in projects_by_version.items() if len(versions) > 1}
if not drift:
    print(f"All {len(projects_by_version)} PyPI packages resolve to one version in every project.")
    sys.exit(0)

lines = [
    f"{name}: "
    + "; ".join(f"{version} in {', '.join(projects)}" for version, projects in versions.items())
    for name, versions in sorted(drift.items())
]
heading = (
    f"{len(drift)} of {len(projects_by_version)} PyPI packages resolve to more than one version"
)
print(heading + ":\n" + "\n".join(f"  {line}" for line in lines))

if os.environ.get("GITHUB_ACTIONS") == "true":
    print(
        f"::warning title=Python version drift::{heading}. Run `uvx --from poethepoet==0.49.0 poe upgrade` to align them."
    )
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
        summary.write(f"### {heading}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
