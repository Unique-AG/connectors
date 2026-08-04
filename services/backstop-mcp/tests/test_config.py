import ssl

import pytest

from backstop_mcp.config import BackstopConfig, DatabaseConfig, normalize_asyncpg_url


class TestNormalizeAsyncpgUrl:
    def test_adds_asyncpg_driver_prefix(self) -> None:
        url, connect_args = normalize_asyncpg_url("postgresql://user:pass@db:5432/backstop")

        assert url == "postgresql+asyncpg://user:pass@db:5432/backstop"
        assert connect_args == {}

    def test_strips_sslmode_verify_and_sets_ssl_context(self) -> None:
        url, connect_args = normalize_asyncpg_url(
            "postgresql://user:pass@db:5432/backstop?sslmode=verify"
        )

        assert url == "postgresql+asyncpg://user:pass@db:5432/backstop"
        ssl_ctx = connect_args.get("ssl")
        assert isinstance(ssl_ctx, ssl.SSLContext)
        assert ssl_ctx.verify_mode == ssl.CERT_REQUIRED

    def test_strips_sslmode_require_without_cert_verification(self) -> None:
        url, connect_args = normalize_asyncpg_url(
            "postgresql://user:pass@db:5432/backstop?sslmode=require"
        )

        assert url == "postgresql+asyncpg://user:pass@db:5432/backstop"
        ssl_ctx = connect_args.get("ssl")
        assert isinstance(ssl_ctx, ssl.SSLContext)
        assert ssl_ctx.verify_mode == ssl.CERT_NONE

    def test_strips_channel_binding(self) -> None:
        url, connect_args = normalize_asyncpg_url(
            "postgresql://user:pass@db:5432/backstop?sslmode=disable&channel_binding=require"
        )

        assert url == "postgresql+asyncpg://user:pass@db:5432/backstop"
        assert connect_args == {}


class TestBackstopConfigDefaults:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # BACKSTOP_BASE_URL may be set in the developer's local .env (loaded by other modules
        # under test); clear it so this test only asserts on this class's own field defaults.
        monkeypatch.delenv("BACKSTOP_BASE_URL", raising=False)
        config = BackstopConfig()

        assert config.base_url == "https://api.backstopsolutions.com"
        assert config.default_timeout_seconds == 30.0
        assert config.reports_timeout_seconds == 120.0
        assert config.max_concurrent_requests_per_user == 5
        assert config.max_retry_attempts == 5
        assert config.max_retry_wait_ms == 30_000
        assert config.default_page_size == 100
        assert config.report_page_size == 500
        assert config.custom_field_overrides == {}

    def test_env_vars_override_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKSTOP_DEFAULT_TIMEOUT_SECONDS", "45.5")
        monkeypatch.setenv("BACKSTOP_REPORTS_TIMEOUT_SECONDS", "90")
        monkeypatch.setenv("BACKSTOP_MAX_CONCURRENT_REQUESTS_PER_USER", "3")
        monkeypatch.setenv("BACKSTOP_MAX_RETRY_ATTEMPTS", "2")
        monkeypatch.setenv("BACKSTOP_MAX_RETRY_WAIT_MS", "5000")
        monkeypatch.setenv("BACKSTOP_DEFAULT_PAGE_SIZE", "50")
        monkeypatch.setenv("BACKSTOP_REPORT_PAGE_SIZE", "250")

        config = BackstopConfig()

        assert config.default_timeout_seconds == 45.5
        assert config.reports_timeout_seconds == 90.0
        assert config.max_concurrent_requests_per_user == 3
        assert config.max_retry_attempts == 2
        assert config.max_retry_wait_ms == 5000
        assert config.default_page_size == 50
        assert config.report_page_size == 250

    def test_report_page_size_rejects_values_over_500(self) -> None:
        with pytest.raises(ValueError, match="report_page_size"):
            BackstopConfig(report_page_size=501)


class TestDatabaseConfigSsl:
    def test_rewrites_helm_database_url_with_sslmode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql://user:pass@db:5432/backstop?sslmode=verify-full",
        )

        config = DatabaseConfig()

        assert config.connection_url == "postgresql+asyncpg://user:pass@db:5432/backstop"
        assert "sslmode" not in config.connection_url
        assert isinstance(config.connect_args.get("ssl"), ssl.SSLContext)
