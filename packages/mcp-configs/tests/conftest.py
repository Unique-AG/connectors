import os

import pytest

_READ_PREFIXES = (
    "DATABASE_URL",
    "DB_",
    "PG_",
    "REDIS_",
    "ZITADEL_",
    "ELICITATION_",
    "UPSTREAM_",
    "MCP_",
    "LOG",
    "HOST",
    "PORT",
)


@pytest.fixture(autouse=True)
def isolated_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """No developer's environment or `.env` file leaks into a test."""
    for name in list(os.environ):
        if name.upper().startswith(_READ_PREFIXES):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
