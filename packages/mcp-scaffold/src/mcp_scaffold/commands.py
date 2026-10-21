"""The commands the scaffold runs in a generated service."""

import os
import subprocess
from pathlib import Path


def check(target: Path) -> None:
    """Format the generated code, then check it as CI does. The generator leaves layout to ruff,
    and pytest records the first tool surface snapshot."""
    run(
        [
            ["uv", "sync"],
            ["uv", "run", "ruff", "format", "--quiet", "."],
            ["uv", "run", "ruff", "check", "--fix", "--quiet", "."],
            ["uv", "run", "ruff", "format", "--quiet", "."],
            ["uv", "run", "basedpyright"],
            ["uv", "run", "lint-imports"],
            ["uv", "run", "pytest", "-q", "--regen-all"],
        ],
        target,
    )


def run(commands: list[list[str]], service: Path) -> None:
    """In the service's own environment, not the scaffold's."""
    environment = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    for command in commands:
        subprocess.run(command, cwd=service, env=environment, check=True)
