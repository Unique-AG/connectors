import pytest


@pytest.fixture(autouse=True)
def isolated_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """No developer's environment or `.env` file leaks into a test."""
    for name in [
        "DATABASE_URL",
        "DB_URL",
        "DB_HOST",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_SSL_ROOT_CERT",
        "PG_DATABASE_SSL_MODE",
        "REDIS_URL",
        "LOG_LEVEL",
        "LOGS_DIAGNOSTICS_DATA_POLICY",
        "HOST",
        "PORT",
        "MCP_BASE_URL",
        "MCP_ALLOWED_ORIGINS",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
