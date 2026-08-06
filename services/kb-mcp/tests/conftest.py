"""Shared test fixtures for kb-mcp."""

import pytest

from kb_mcp.settings import get_settings

# Minimal valid env so get_settings() succeeds by default in every test
# without each test needing to stub out required config. Tests that care
# about a specific value (frontend_base_url, storage mode, ...) override it
# via monkeypatch.setenv + get_settings.cache_clear(), or patch get_settings
# directly at the call site.
_DEFAULT_TEST_ENV = {
    "ZITADEL_BASE_URL": "https://id.test.unique.app",
    "ZITADEL_CLIENT_ID": "test-client-id",
    "ZITADEL_CLIENT_SECRET": "test-client-secret",
    "ALLOW_EPHEMERAL_OAUTH_STORAGE": "true",
}


@pytest.fixture(autouse=True)
def _reset_settings_cache(monkeypatch):
    for key, value in _DEFAULT_TEST_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
