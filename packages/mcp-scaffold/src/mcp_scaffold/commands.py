"""The commands the scaffold runs in a generated service."""

import os
import subprocess
from pathlib import Path


def check(target: Path) -> None:
    """Format the generated code, then check it. The generator leaves layout to ruff, and pytest
    records the first tool surface snapshot."""
    run(
        [
            ["uv", "sync"],
            ["uv", "run", "ruff", "format", "--quiet", "."],
            ["uv", "run", "ruff", "check", "--fix", "--quiet", "."],
            ["uv", "run", "ruff", "format", "--quiet", "."],
            ["uv", "run", "basedpyright"],
            ["uv", "run", "pytest", "-q", "--regen-all"],
        ],
        target,
    )


def run(commands: list[list[str]], service: Path) -> None:
    """In the service's own environment, not the scaffold's."""
    environment = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    _link_project_environment(service, environment.get("UV_PROJECT_ENVIRONMENT"))
    for command in commands:
        subprocess.run(command, cwd=service, env=environment, check=True)


def _link_project_environment(service: Path, environment: str | None) -> None:
    """uv honours UV_PROJECT_ENVIRONMENT, but the service's basedpyright reads `.venv`, and
    resolves no import without it. A link makes both see the one environment."""
    venv = service / ".venv"
    if environment is None or venv.exists():
        return
    shared = service / environment
    shared.mkdir(parents=True, exist_ok=True)
    venv.symlink_to(shared, target_is_directory=True)
