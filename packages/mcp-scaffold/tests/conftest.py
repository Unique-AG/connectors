import os
from collections.abc import Callable
from pathlib import Path

import pytest

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


@pytest.fixture
def use_venv(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> UseVenv:
    def use(service: str) -> None:
        monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(venvs(request.config) / service))

    return use
