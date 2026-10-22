"""`mcp-architecture-lint`: ruff on the MCP in the current folder, first with `code_style.toml`
passed as `--config`, so nothing in the MCP changes what it checks, then with the MCP's own
configuration, for the rules it adds."""

import argparse
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from typing import cast

from ruff.__main__ import find_ruff_bin

CODE_STYLE = str(files("mcp_architecture").joinpath("code_style.toml"))

type Finding = tuple[str, int, int, str]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mcp-architecture-lint",
        description="Format and lint the MCP in the current folder as CI does.",
    )
    parser.add_argument("--fix", action="store_true", help="format and fix what ruff can")
    sys.exit(lint(Path.cwd(), fix=cast(bool, parser.parse_args().fix)))


def lint(root: Path, *, fix: bool = False) -> int:
    """1 when the shared code style or a rule the MCP adds finds something, or the code is not
    formatted, else 0. Also prints what the MCP's own configuration hides from its editor."""
    shared = ["--config", CODE_STYLE]
    if fix:
        _ruff(root, "check", "--fix", "--silent", *shared)
        _ruff(root, "check", "--fix", "--silent")
    formatted = _ruff(root, "format", *([] if fix else ["--check"]), *shared)
    checked = _ruff(root, "check", *shared)
    strict = _findings(root, *shared)
    own = _findings(root)
    if strict is None or own is None:
        return 1
    added = sorted(own.keys() - strict.keys())
    if added:
        print("\nRules the MCP's [tool.ruff] adds find:")
        print("\n".join(own[finding] for finding in added))
    if hidden := sorted({code for *_, code in strict.keys() - own.keys()}):
        print(
            f"\nThe MCP's editor and a bare `ruff check` miss {hidden}: its [tool.ruff], a "
            "ruff.toml or .ruff.toml, or an .ignore hides them. The rules come from "
            "mcp_architecture/code_style.toml. Remove what hides them."
        )
    return 1 if formatted or checked or added else 0


def _ruff(root: Path, *arguments: str) -> int:
    return subprocess.run([find_ruff_bin(), *arguments, "."], cwd=root, check=False).returncode


def _findings(root: Path, *arguments: str) -> dict[Finding, str] | None:
    """Each finding, as ruff prints it in one line, or None when ruff cannot read the
    configuration."""
    result = subprocess.run(
        [find_ruff_bin(), "check", "--output-format=json", *arguments, "."],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        print(result.stderr, file=sys.stderr)
        return None
    findings: dict[Finding, str] = {}
    for found in cast(list[dict[str, object]], json.loads(result.stdout)):
        location = cast(dict[str, int], found["location"])
        path = Path(str(found["filename"])).relative_to(root.resolve()).as_posix()
        key = (path, location["row"], location["column"], str(found["code"]))
        findings[key] = f"{path}:{key[1]}:{key[2]}: {key[3]} {found['message']}"
    return findings
