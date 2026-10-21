"""Generate a new MCP: the shared skeleton with the layers it asks for. `cli.py` runs it, and
`services/architecture-demo-mcp` is its output with a worked example on top."""

from datetime import UTC, datetime
from pathlib import Path

from mcp_scaffold.agents import describe_mcp
from mcp_scaffold.commands import check
from mcp_scaffold.openapi import VendorSpec, generate_operations, write_spec
from mcp_scaffold.options import Options
from mcp_scaffold.persistence import write_persistence
from mcp_scaffold.pins import scaffold_version
from mcp_scaffold.pyproject import edit_pyproject
from mcp_scaffold.repository import register
from mcp_scaffold.skeleton import copy_skeleton, rename, render_templates
from mcp_scaffold.stamp import stamp, written_files
from mcp_scaffold.upstream import write_upstream


def scaffold(options: Options, repo: Path, *, release: bool = True) -> Path:
    """Generate `services/<name>` in `repo` and register it there.

    Every step writes the skeleton's placeholder names, which `rename` replaces once all of them
    have run. The codegen runs after it, since it needs the service installed under its name.
    Every file the scaffold wrote is stamped with its version and the moment the run started.
    """
    started = datetime.now(UTC)
    target = repo / "services" / options.name
    assert not target.exists(), f"{target} already exists"
    spec = VendorSpec.load(options.spec, repo) if options.spec is not None else None

    copy_skeleton(target)
    write_upstream(options, target)
    write_persistence(options, target)
    render_templates(options, target)
    edit_pyproject(options, target, repo)
    if spec is not None:
        write_spec(spec, target)
    describe_mcp(options, target)
    rename(options, target)
    register(options, repo, release=release)
    written = set(written_files(target))
    if spec is not None:
        written.add(generate_operations(options, target))
    stamp(sorted(written), version=scaffold_version(), timestamp=started)
    check(target)
    return target
