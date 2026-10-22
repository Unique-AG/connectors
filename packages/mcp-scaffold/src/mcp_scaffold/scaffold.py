"""Generate a new MCP: the shared skeleton with the layers it asks for. `cli.py` runs it."""

from datetime import UTC, datetime
from pathlib import Path

from mcp_scaffold.commands import check
from mcp_scaffold.openapi import VendorSpec, generate_operations, write_spec
from mcp_scaffold.options import Options
from mcp_scaffold.persistence import write_persistence
from mcp_scaffold.pyproject import dependencies
from mcp_scaffold.repository import register
from mcp_scaffold.skeleton import copy_skeleton, rename, render_templates
from mcp_scaffold.stamp import stamp, written_files
from mcp_scaffold.upstream import write_upstream


def scaffold(
    options: Options, repo: Path, *, spec: VendorSpec | None, commit: str, release: bool = True
) -> Path:
    """Generate `services/<name>` in `repo` and register it there. `spec` is the vendor's spec
    `load_spec` read from `options.spec`, for an OpenAPI upstream.

    Every step writes the skeleton's placeholder names, which `rename` replaces once all of them
    have run. The codegen runs after it, since it needs the service installed under its name.
    Every file the scaffold wrote is stamped with `commit`, the one it runs from, and the moment
    the run started.
    """
    started = datetime.now(UTC)
    target = repo / "services" / options.name
    assert not target.exists(), f"{target} already exists"
    assert (spec is None) == (options.spec is None), "load the spec options.spec names"

    copy_skeleton(target)
    write_upstream(options, target)
    write_persistence(options, target)
    render_templates(
        target,
        options=options,
        spec=spec,
        api_url=spec.api_url if spec is not None and spec.api_url else _EXAMPLE_API_URL,
        dependencies=dependencies(options, repo),
    )
    if spec is not None:
        write_spec(spec, target)
    rename(options, target)
    register(options, repo, release=release)
    written = set(written_files(target))
    if spec is not None:
        written.add(generate_operations(options, target))
    stamp(sorted(written), commit=commit, timestamp=started)
    check(target, openapi=spec is not None)
    return target


def load_spec(options: Options, repo: Path) -> VendorSpec | None:
    return VendorSpec.load(options.spec, repo) if options.spec is not None else None


# The upstream settings' default, when the spec names no server.
_EXAMPLE_API_URL = "https://api.example.com"
