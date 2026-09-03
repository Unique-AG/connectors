"""Shared test fixtures for kb-mcp."""

from pathlib import Path

import pytest

from kb_mcp.settings import Settings, get_settings

# Fixed, committed test env — never the developer's real .env. Set as real
# process env vars too (not just the dotenv override below) so tests that
# construct Settings(_env_file=None) directly still get these defaults.
# Tests that care about a specific value (frontend_base_url, storage mode,
# ...) override it via monkeypatch.setenv + get_settings.cache_clear(), or
# patch get_settings directly at the call site.
_TEST_ENV_FILE = Path(__file__).parent.parent / "test.env"
_DEFAULT_TEST_ENV = {
    "ZITADEL_BASE_URL": "https://id.test.unique.app",
    "ZITADEL_CLIENT_ID": "test-client-id",
    "ZITADEL_JWT_SIGNING_KEY": "test-jwt-signing-key",
    "ALLOW_EPHEMERAL_OAUTH_STORAGE": "true",
}


@pytest.fixture(autouse=True)
def _reset_settings_cache(monkeypatch):
    # A real .env (e.g. a live DATABASE_URL added for manual Postgres
    # testing) must never change what Settings() resolves to in a test.
    monkeypatch.setitem(Settings.model_config, "env_file", _TEST_ENV_FILE)
    for key, value in _DEFAULT_TEST_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
