import ssl
from datetime import timedelta

import pytest
from pydantic import ValidationError

from backstop_mcp.config import (
    ActivityHistoryConfig,
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
        assert config.custom_field_schema_ttl_minutes == 120
        assert config.opportunity_stage_ttl_minutes == 60
        assert config.activity_tag_ttl_minutes == 24 * 60
        assert config.system_user_ttl_minutes == 24 * 60
        # Custom-field catalogs ship on (measured 6.15 s walk). The other two stay off until
        # their histograms say otherwise — see `features/cached_catalog.py`.
        assert config.custom_field_schema_cache_enabled is True
        assert config.activity_tag_cache_enabled is False
        assert config.system_user_cache_enabled is False
        assert config.employment_relationship_type_ids == ()
        assert config.employment_relationship_type_markers == ("employ",)
        assert config.former_employment_relationship_type_ids == ()
        assert config.former_employment_relationship_type_markers == (
            "former",
            "previous",
            "ex-",
            "no longer",
        )

    def test_strips_trailing_slash_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKSTOP_BASE_URL", "https://tenant.backstopsolutions.com/")

        config = BackstopConfig()

        assert config.base_url == "https://tenant.backstopsolutions.com"

    def test_rejects_malformed_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKSTOP_BASE_URL", "not a url")

        with pytest.raises(ValidationError):
            BackstopConfig()

    def test_env_vars_override_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKSTOP_DEFAULT_TIMEOUT_SECONDS", "45.5")
        monkeypatch.setenv("BACKSTOP_REPORTS_TIMEOUT_SECONDS", "90")
        monkeypatch.setenv("BACKSTOP_MAX_CONCURRENT_REQUESTS_PER_USER", "3")
        monkeypatch.setenv("BACKSTOP_MAX_RETRY_ATTEMPTS", "2")
        monkeypatch.setenv("BACKSTOP_MAX_RETRY_WAIT_MS", "5000")
        monkeypatch.setenv("BACKSTOP_DEFAULT_PAGE_SIZE", "50")
        monkeypatch.setenv("BACKSTOP_REPORT_PAGE_SIZE", "250")
        monkeypatch.setenv("BACKSTOP_CUSTOM_FIELD_SCHEMA_TTL_MINUTES", "60")
        monkeypatch.setenv("BACKSTOP_OPPORTUNITY_STAGE_TTL_MINUTES", "30")
        monkeypatch.setenv("BACKSTOP_ACTIVITY_TAG_TTL_MINUTES", "90")
        monkeypatch.setenv("BACKSTOP_SYSTEM_USER_TTL_MINUTES", "45")
        monkeypatch.setenv("BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED", "true")
        monkeypatch.setenv("BACKSTOP_ACTIVITY_TAG_CACHE_ENABLED", "1")
        monkeypatch.setenv("BACKSTOP_SYSTEM_USER_CACHE_ENABLED", "yes")

        config = BackstopConfig()

        assert config.default_timeout_seconds == 45.5
        assert config.reports_timeout_seconds == 90.0
        assert config.max_concurrent_requests_per_user == 3
        assert config.max_retry_attempts == 2
        assert config.max_retry_wait_ms == 5000
        assert config.default_page_size == 50
        assert config.report_page_size == 250
        assert config.custom_field_schema_ttl_minutes == 60
        assert config.opportunity_stage_ttl_minutes == 30
        assert config.activity_tag_ttl_minutes == 90
        assert config.system_user_ttl_minutes == 45
        # Each catalog cache is turned on per feature, and pydantic-settings accepts the several
        # spellings an operator or a Helm values file is likely to produce.
        assert config.custom_field_schema_cache_enabled is True
        assert config.activity_tag_cache_enabled is True
        assert config.system_user_cache_enabled is True

    def test_employment_relationship_types_parse_csv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_IDS", "1, 2,3")
        monkeypatch.setenv("BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS", "Employment, Works At")
        monkeypatch.setenv("BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_IDS", "9")
        monkeypatch.setenv("BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS", "Used To Work")

        config = BackstopConfig()

        assert config.employment_relationship_type_ids == ("1", "2", "3")
        assert config.employment_relationship_type_markers == ("Employment", "Works At")
        assert config.former_employment_relationship_type_ids == ("9",)
        assert config.former_employment_relationship_type_markers == ("Used To Work",)

    def test_configured_markers_replace_the_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A tenant's phrasing is the whole vocabulary; an empty value leaves ids to decide."""
        monkeypatch.setenv(
            "BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS", "Placement Ended"
        )
        assert BackstopConfig().former_employment_relationship_type_markers == ("Placement Ended",)

        monkeypatch.setenv("BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS", "")
        assert BackstopConfig().former_employment_relationship_type_markers == ()

    def test_report_page_size_rejects_values_over_500(self) -> None:
        with pytest.raises(ValueError, match="report_page_size"):
            BackstopConfig(report_page_size=501)

    def test_custom_field_schema_ttl_caps_values_over_24_hours(self) -> None:
        config = BackstopConfig(custom_field_schema_ttl_minutes=24 * 60 + 1)
        assert config.custom_field_schema_ttl_minutes == 24 * 60

    def test_custom_field_schema_ttl_caps_legacy_week_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BACKSTOP_CUSTOM_FIELD_SCHEMA_TTL_MINUTES", "10080")
        assert BackstopConfig().custom_field_schema_ttl_minutes == 24 * 60

    def test_custom_field_schema_ttl_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="custom_field_schema_ttl_minutes"):
            BackstopConfig(custom_field_schema_ttl_minutes=0)

    def test_activity_tag_ttl_rejects_values_over_24_hours(self) -> None:
        with pytest.raises(ValueError, match="activity_tag_ttl_minutes"):
            BackstopConfig(activity_tag_ttl_minutes=24 * 60 + 1)

    def test_activity_tag_ttl_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="activity_tag_ttl_minutes"):
            BackstopConfig(activity_tag_ttl_minutes=0)

    def test_system_user_ttl_rejects_values_over_24_hours(self) -> None:
        with pytest.raises(ValueError, match="system_user_ttl_minutes"):
            BackstopConfig(system_user_ttl_minutes=24 * 60 + 1)

    def test_system_user_ttl_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="system_user_ttl_minutes"):
            BackstopConfig(system_user_ttl_minutes=0)


class TestActivityHistoryConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ACTIVITY_HISTORY_PAGE_SIZE", raising=False)
        monkeypatch.delenv("ACTIVITY_HISTORY_GIST_CHARS", raising=False)

        config = ActivityHistoryConfig()

        assert config.page_size == 10
        assert config.gist_chars == 300

    def test_env_vars_override_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACTIVITY_HISTORY_PAGE_SIZE", "25")
        monkeypatch.setenv("ACTIVITY_HISTORY_GIST_CHARS", "500")

        config = ActivityHistoryConfig()

        assert config.page_size == 25
        assert config.gist_chars == 500

    def test_page_size_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="page_size"):
            ActivityHistoryConfig(page_size=0)

    def test_gist_chars_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="gist_chars"):
            ActivityHistoryConfig(gist_chars=0)


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


class TestPublicBaseUrl:
    """The OAuth issuer clients are redirected to, so a leftover local default is a dead deploy."""

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


class TestEncryptionConfig:
    def test_requires_an_encryption_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BACKSTOP_MCP_ENCRYPTION_KEY", raising=False)

        with pytest.raises(ValueError, match="BACKSTOP_MCP_ENCRYPTION_KEY"):
            EncryptionConfig()

    def test_accepts_a_configured_key(self) -> None:
        config = EncryptionConfig(encryption_key="a-key")  # pyright: ignore[reportArgumentType]

        assert config.encryption_key is not None
        assert config.encryption_key.get_secret_value() == "a-key"
