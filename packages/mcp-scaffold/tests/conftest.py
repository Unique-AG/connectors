from collections.abc import Callable
from pathlib import Path

import pytest

type UseVenv = Callable[[str], None]


@pytest.fixture
def use_venv(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> UseVenv:
    """Gives a generated service a `.venv` kept between runs, under `.pytest_cache`.

    In the service's folder, each run's temp directory would hold a 3 GB set of `.venv`s that
    pytest deletes runs later, for half a minute each. The scaffold passes the variable on to uv.
    """
    cache = request.config.cache
    assert cache is not None, "the cacheprovider plugin keeps the venvs"
    venvs = Path(cache.mkdir("venvs"))

    def use(service: str) -> None:
        monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(venvs / service))

    return use
