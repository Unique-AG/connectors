import ssl
from datetime import timedelta

import pytest
from pydantic import SecretStr

from backstop_mcp.config import (
    AuthConfig,
    BackstopConfig,
    DatabaseConfig,
    normalize_asyncpg_url,
)


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
        assert config.custom_field_schema_ttl_minutes == 7 * 24 * 60

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

    def test_schema_ttl_rejects_zero(self) -> None:
        """A zero TTL would refetch the whole schema on every call."""
        with pytest.raises(ValueError, match="custom_field_schema_ttl_minutes"):
            BackstopConfig(custom_field_schema_ttl_minutes=0)


class TestAuthConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTH_TOKEN_RETENTION_DAYS", raising=False)
        monkeypatch.delenv("AUTH_CLEANUP_INTERVAL_HOURS", raising=False)

        config = AuthConfig()

        assert config.token_retention_days == 30
        assert config.token_retention == timedelta(days=30)
        assert config.cleanup_interval_hours == 6.0
        assert config.cleanup_interval == timedelta(hours=6)

    def test_env_vars_override_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTH_TOKEN_RETENTION_DAYS", "7")
        monkeypatch.setenv("AUTH_CLEANUP_INTERVAL_HOURS", "0.5")

        config = AuthConfig()

        assert config.token_retention == timedelta(days=7)
        assert config.cleanup_interval == timedelta(minutes=30)

    def test_zero_retention_is_rejected(self) -> None:
        """Retaining nothing would delete a token family the moment it expired."""
        with pytest.raises(ValueError, match="token_retention_days"):
            AuthConfig(token_retention_days=0)

    def test_zero_interval_is_rejected(self) -> None:
        """A zero interval would spin the sweep loop without ever sleeping."""
        with pytest.raises(ValueError, match="cleanup_interval_hours"):
            AuthConfig(cleanup_interval_hours=0)


class TestBackstopServiceAccount:
    def test_absent_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BACKSTOP_SERVICE_USERNAME", raising=False)
        monkeypatch.delenv("BACKSTOP_SERVICE_API_TOKEN", raising=False)
        config = BackstopConfig()

        assert config.service_username is None
        assert config.service_api_token is None

    def test_reads_both_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKSTOP_SERVICE_USERNAME", "svc-bot")
        monkeypatch.setenv("BACKSTOP_SERVICE_API_TOKEN", "svc-token")
        config = BackstopConfig()

        assert config.service_username == "svc-bot"
        assert config.service_api_token is not None
        assert config.service_api_token.get_secret_value() == "svc-token"

    def test_rejects_username_without_token(self) -> None:
        with pytest.raises(ValueError, match="must be set together"):
            BackstopConfig(service_username="svc-bot")

    def test_rejects_token_without_username(self) -> None:
        with pytest.raises(ValueError, match="must be set together"):
            BackstopConfig(service_api_token=SecretStr("svc-token"))


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
