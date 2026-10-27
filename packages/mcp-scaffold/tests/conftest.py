import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from mcp_scaffold.commands import run

type UseVenv = Callable[[str], None]

REPO = Path(__file__).parents[3]
# What the scaffold registers a new MCP in. The tests register in copies.
REGISTRIES = [
    ".gitcommitizen",
    "release-please-config.json",
    ".release-please-manifest.json",
    ".github/workflows/release-rerun.yaml",
    "pnpm-workspace.yaml",
]
# What a developer's shell may export, which a generated service's tests must not read.
DEVELOPER_ENVIRONMENT = {
    "HOST": "myhost.local",
    "PORT": "9000",
    "MCP_BASE_URL": "https://mcp.other.example.com",
    "MCP_ALLOWED_ORIGINS": '["https://other.example.com"]',
    "UPSTREAM_API_URL": "https://api.other.example.com",
    "UPSTREAM_TIMEOUT_SECONDS": "1",
    "UPSTREAM_RETRY_MAX_ATTEMPTS": "1",
    "UPSTREAM_RETRY_MAX_WAIT_SECONDS": "60",
    "UPSTREAM_VERIFY_PATH": "/other",
    "MCP_AUTH_MAX_FAILED_SIGN_INS": "1",
    "MCP_AUTH_ACCESS_TOKEN_MINUTES": "1",
}


def copy_registries(repo: Path) -> None:
    for registry in REGISTRIES:
        (repo / registry).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / registry, repo / registry)


def venvs(config: pytest.Config) -> Path:
    """Where a generated service's `.venv` is kept between runs, under `.pytest_cache`.

    In the service's folder, each run's temp directory would hold a 3 GB set of `.venv`s that
    pytest deletes runs later, for half a minute each. The scaffold passes UV_PROJECT_ENVIRONMENT
    on to uv.
    """
    cache = config.cache
    assert cache is not None, "the cacheprovider plugin keeps the venvs"
    return Path(cache.mkdir("venvs"))


def link_project_environment(service: Path) -> None:
    """uv honours UV_PROJECT_ENVIRONMENT, but the service's basedpyright reads `.venv`, and
    resolves no import without it. A link makes both see the one environment."""
    venv = service / ".venv"
    if venv.exists():
        return
    shared = Path(os.environ["UV_PROJECT_ENVIRONMENT"])
    shared.mkdir(parents=True, exist_ok=True)
    venv.symlink_to(shared, target_is_directory=True)


def run_linked(commands: list[list[str]], service: Path) -> None:
    """`commands.run`, with the service's `.venv` linked to UV_PROJECT_ENVIRONMENT first."""
    link_project_environment(service)
    run(commands, service)


@pytest.fixture
def use_venv(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> UseVenv:
    def use(service: str) -> None:
        monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(venvs(request.config) / service))

    return use
