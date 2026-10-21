"""The commands the scaffold runs in a generated service."""

import os
import subprocess
from pathlib import Path


def check(target: Path, *, openapi: bool) -> None:
    """Format the generated code, then check it as `scripts/check-python-service.sh` does, but
    for biome. The generator leaves layout to ruff, and `mcp-architecture-check` records the first
    tool surface snapshot."""
    run(
        [
            ["uv", "sync"],
            ["uv", "run", "ruff", "format", "--quiet", "."],
            ["uv", "run", "ruff", "check", "--fix", "--quiet", "."],
            ["uv", "run", "ruff", "format", "--quiet", "."],
            *([["uv", "run", "mcp-openapi-codegen", "--check"]] if openapi else []),
            ["uv", "run", "basedpyright"],
            ["uv", "run", "lint-imports"],
            ["uv", "run", "mcp-architecture-check", "--update"],
            ["uv", "run", "pytest", "-q"],
        ],
        target,
    )


def run(commands: list[list[str]], service: Path) -> None:
    """In the service's own environment, not the scaffold's."""
    environment = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    for command in commands:
        subprocess.run(command, cwd=service, env=environment, check=True)
