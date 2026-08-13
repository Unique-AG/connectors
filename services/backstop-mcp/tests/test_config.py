import ssl

import pytest
from pydantic import ValidationError

from backstop_mcp.config import (
    AppConfig,
    AppEnv,
    AuthConfig,
    BackstopConfig,
    DatabaseConfig,
    EncryptionConfig,
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
        assert ssl_ctx.check_hostname is True

    def test_strips_sslmode_verify_ca_without_hostname_check(self) -> None:
        url, connect_args = normalize_asyncpg_url(
            "postgresql://user:pass@db:5432/backstop?sslmode=verify-ca"
        )

        assert url == "postgresql+asyncpg://user:pass@db:5432/backstop"
        ssl_ctx = connect_args.get("ssl")
        assert isinstance(ssl_ctx, ssl.SSLContext)
        assert ssl_ctx.verify_mode == ssl.CERT_REQUIRED
        assert ssl_ctx.check_hostname is False

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

    def test_rejects_non_postgres_schemes(self) -> None:
        with pytest.raises(ValueError, match="PostgreSQL"):
            normalize_asyncpg_url("mysql://user:pass@db:3306/backstop")


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
        assert config.page_limit_param == "page[limit]"
        assert config.page_offset_param == "page[offset]"

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKSTOP_BASE_URL", "https://tenant.backstopsolutions.com")

        config = BackstopConfig()

        assert config.base_url == "https://tenant.backstopsolutions.com"

    def test_strips_trailing_slash_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKSTOP_BASE_URL", "https://tenant.backstopsolutions.com/")

        config = BackstopConfig()

        assert config.base_url == "https://tenant.backstopsolutions.com"

    def test_rejects_malformed_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKSTOP_BASE_URL", "not a url")

        with pytest.raises(ValidationError):
            BackstopConfig()

    def test_client_tuning_knobs_are_overridable_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BACKSTOP_DEFAULT_TIMEOUT_SECONDS", "11")
        monkeypatch.setenv("BACKSTOP_REPORTS_TIMEOUT_SECONDS", "222")
        monkeypatch.setenv("BACKSTOP_MAX_CONCURRENT_REQUESTS_PER_USER", "3")
        monkeypatch.setenv("BACKSTOP_MAX_RETRY_ATTEMPTS", "2")
        monkeypatch.setenv("BACKSTOP_MAX_RETRY_WAIT_MS", "5000")
        monkeypatch.setenv("BACKSTOP_DEFAULT_PAGE_SIZE", "33")
        monkeypatch.setenv("BACKSTOP_REPORT_PAGE_SIZE", "444")
        monkeypatch.setenv("BACKSTOP_PAGE_LIMIT_PARAM", "limit")
        monkeypatch.setenv("BACKSTOP_PAGE_OFFSET_PARAM", "offset")

        config = BackstopConfig()

        assert config.default_timeout_seconds == 11.0
        assert config.reports_timeout_seconds == 222.0
        assert config.max_concurrent_requests_per_user == 3
        assert config.max_retry_attempts == 2
        assert config.max_retry_wait_ms == 5_000
        assert config.default_page_size == 33
        assert config.report_page_size == 444
        assert config.page_limit_param == "limit"
        assert config.page_offset_param == "offset"


class TestPublicBaseUrl:
    """The OAuth issuer clients get redirected to, so a leftover local default is a dead deploy."""

    def test_the_local_default_is_allowed_outside_production(self) -> None:
        config = AppConfig(app_env=AppEnv.DEVELOPMENT)

        assert config.issuer == "http://localhost:9010"

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:9010",
            "http://127.0.0.1:9010",
            "http://[::1]:9010",
            # A bind address, not somewhere a client can reach this service.
            "http://0.0.0.0:9010",
        ],
    )
    def test_production_rejects_a_url_no_client_can_reach(self, url: str) -> None:
        with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
            AppConfig.model_validate({"app_env": AppEnv.PRODUCTION, "public_base_url": url})

    def test_rejects_malformed_public_base_url(self) -> None:
        with pytest.raises(ValidationError):
            AppConfig.model_validate(
                {"app_env": AppEnv.DEVELOPMENT, "public_base_url": "not-a-url"}
            )

    def test_production_accepts_a_real_public_url(self) -> None:
        config = AppConfig.model_validate(
            {"app_env": AppEnv.PRODUCTION, "public_base_url": "https://backstop-mcp.example"}
        )

        assert config.issuer == "https://backstop-mcp.example"

    def test_the_issuer_never_carries_a_trailing_slash(self) -> None:
        config = AppConfig.model_validate(
            {"app_env": AppEnv.PRODUCTION, "public_base_url": "https://backstop-mcp.example/"}
        )

        assert config.issuer == "https://backstop-mcp.example"

    def test_the_parsed_url_is_available_for_host_and_scheme_checks(self) -> None:
        config = AppConfig.model_validate(
            {"app_env": AppEnv.PRODUCTION, "public_base_url": "https://backstop-mcp.example"}
        )

        assert config.public_base_url.scheme == "https"
        assert config.public_base_url.host == "backstop-mcp.example"

    def test_production_is_the_default_env_so_the_bare_default_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`app_env` defaults to production, so an unconfigured deploy fails at startup."""
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

        with pytest.raises(ValueError, match="PUBLIC_BASE_URL"):
            AppConfig()


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

    def test_builds_url_from_discrete_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DB_URL", raising=False)

        config = DatabaseConfig(
            host="db",
            port=5432,
            name="backstop",
            user="user",
            password="p@ss",
        )

        assert config.connection_url == "postgresql+asyncpg://user:p%40ss@db:5432/backstop"

    def test_missing_parts_list_all_absent_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DB_URL", raising=False)

        with pytest.raises(ValidationError, match="DB_HOST"):
            DatabaseConfig()


class TestAuthConfigDefaults:
    def test_defaults(self) -> None:
        config = AuthConfig()

        assert config.token_retention_days == 30
        assert config.unused_client_retention_hours == 24.0
        assert config.cleanup_interval_hours == 6.0
        assert config.login_max_attempts == 10
        assert config.login_attempt_window_minutes == 15

    def test_derived_timedeltas(self) -> None:
        config = AuthConfig(
            token_retention_days=1,
            unused_client_retention_hours=2.0,
            cleanup_interval_hours=3.0,
            login_attempt_window_minutes=4,
        )

        assert config.token_retention.days == 1
        assert config.unused_client_retention.total_seconds() == 2.0 * 3600
        assert config.cleanup_interval.total_seconds() == 3.0 * 3600
        assert config.login_attempt_window.total_seconds() == 4 * 60


class TestEncryptionConfig:
    def test_requires_an_encryption_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BACKSTOP_MCP_ENCRYPTION_KEY", raising=False)

        with pytest.raises(ValueError, match="BACKSTOP_MCP_ENCRYPTION_KEY"):
            EncryptionConfig()

    def test_accepts_a_configured_key(self) -> None:
        config = EncryptionConfig(encryption_key="a-key")  # pyright: ignore[reportArgumentType]

        assert config.encryption_key is not None
        assert config.encryption_key.get_secret_value() == "a-key"
