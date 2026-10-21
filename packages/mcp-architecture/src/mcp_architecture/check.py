"""`mcp-architecture-check`: the checks of what a client sees, run outside pytest, so nothing in a
service's `conftest.py` can skip, xfail or deselect them."""

import argparse
import asyncio
import difflib
import importlib.util
import sys
import tomllib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import cast

from fastmcp import FastMCP

from mcp_architecture.settings import settings_showing_input_in_errors
from mcp_architecture.tools import (
    masks_error_details,
    tool_surface,
    tools_with_a_root_combinator,
    undescribed_tools,
)

OFFLINE_SERVER = Path("tests") / "offline_server.py"
SNAPSHOT = Path("tests") / "tool_surface.generated.json"

type ServerFactory = Callable[[], AbstractAsyncContextManager[FastMCP]]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mcp-architecture-check",
        description="Check what a client sees of the MCP in the current folder.",
    )
    parser.add_argument(
        "--update", action="store_true", help=f"write {SNAPSHOT} instead of comparing with it"
    )
    update = cast(bool, parser.parse_args().update)
    findings = asyncio.run(check_service(Path.cwd(), update=update))
    print("\n\n".join(findings) if findings else "Every architecture check passed.")
    sys.exit(1 if findings else 0)


async def check_service(root: Path, *, update: bool = False) -> list[str]:
    """Each way the MCP at `root` breaks a rule, as a message that says how to fix it.

    The server comes from `offline_server()` in `tests/offline_server.py`, an async context
    manager that builds it with fakes in place of the upstream and the stores.
    """
    pyproject = cast(
        dict[str, dict[str, object]], tomllib.loads((root / "pyproject.toml").read_text())
    )
    package = str(pyproject["project"]["name"]).replace("-", "_")
    findings = _root_package_findings(pyproject, package)
    factory = _offline_server(root / OFFLINE_SERVER)
    if factory is None:
        findings.append(
            f"{OFFLINE_SERVER} has no `offline_server()`: the checks list the tools of the server "
            "it builds."
        )
    else:
        async with factory() as server:
            findings.extend(await _server_findings(server))
            findings.extend(_snapshot_findings(root / SNAPSHOT, await tool_surface(server), update))
    shown = settings_showing_input_in_errors(package)
    if shown:
        findings.append(f"Build the model_config of these with mcp_configs.shared_config: {shown}")
    return findings


def _root_package_findings(pyproject: dict[str, dict[str, object]], package: str) -> list[str]:
    """import-linter checks only `root_package`, so it has to be the package the project ships."""
    tool = cast(dict[str, dict[str, object]], pyproject.get("tool", {}))
    root_package = tool.get("importlinter", {}).get("root_package")
    if root_package == package:
        return []
    return [
        f"[tool.importlinter] root_package is {root_package!r}, not the project's package "
        f"{package!r}, so `lint-imports` does not check the MCP's own code."
    ]


def _offline_server(path: Path) -> ServerFactory | None:
    """Loaded from its file, so a `tests` package already imported cannot stand in for it."""
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("mcp_architecture_offline_server", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory: object = getattr(module, "offline_server", None)
    return cast(ServerFactory, factory) if callable(factory) else None


async def _server_findings(server: FastMCP) -> list[str]:
    findings: list[str] = []
    if missing := await undescribed_tools(server):
        findings.append(f"Give these a docstring or a Field(description=...): {missing}")
    if combined := await tools_with_a_root_combinator(server):
        findings.append(
            f"Some clients reject these tools, make their input a plain object: {combined}"
        )
    if not masks_error_details(server):
        findings.append("Create the server with mask_error_details=True.")
    return findings


def _snapshot_findings(snapshot: Path, surface: str, update: bool) -> list[str]:
    if update:
        snapshot.write_text(surface)
        return []
    if not snapshot.is_file():
        return [f"{SNAPSHOT} is missing. Run `uv run mcp-architecture-check --update`."]
    recorded = snapshot.read_text()
    if recorded == surface:
        return []
    diff = difflib.unified_diff(
        recorded.splitlines(keepends=True),
        surface.splitlines(keepends=True),
        fromfile=str(SNAPSHOT),
        tofile="served",
    )
    return [
        f"What a client sees no longer matches {SNAPSHOT}. If you meant the change, run "
        f"`uv run mcp-architecture-check --update` and commit it.\n{''.join(diff)}"
    ]
