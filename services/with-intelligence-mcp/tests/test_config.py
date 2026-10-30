"""Config parsing, and the failures it turns into startup errors."""

import ssl

import pytest
from mcp_credential_auth import DEFAULT_ALLOWED_REDIRECT_HOSTS
from pydantic import ValidationError

from with_intelligence_mcp.config import (
    AppConfig,
    AppEnv,
    AssetClassGroup,
    AuthConfig,
    DatabaseConfig,
    WithIntelligenceConfig,
    normalize_asyncpg_url,
)


class TestAppConfig:
    def test_defaults_to_the_local_port(self) -> None:
        config = AppConfig(app_env=AppEnv.DEVELOPMENT)
        assert config.port == 9011

    def test_rejects_a_loopback_issuer_in_production(self) -> None:
        with pytest.raises(ValidationError, match="PUBLIC_BASE_URL"):
            AppConfig(app_env=AppEnv.PRODUCTION)

    def test_allows_a_loopback_issuer_outside_production(self) -> None:
        config = AppConfig(app_env=AppEnv.DEVELOPMENT)
        assert config.issuer == "http://localhost:9011"

    def test_accepts_a_real_issuer_in_production(self) -> None:
        config = AppConfig.model_validate(
            {"app_env": AppEnv.PRODUCTION, "public_base_url": "https://wi.example.com"}
        )
        assert config.issuer == "https://wi.example.com"

    def test_rejects_http_for_a_real_issuer_in_production(self) -> None:
        with pytest.raises(ValidationError, match="HTTPS"):
            AppConfig.model_validate(
                {"app_env": AppEnv.PRODUCTION, "public_base_url": "http://wi.example.com"}
            )

    def test_issuer_has_no_trailing_slash(self) -> None:
        config = AppConfig.model_validate(
            {"app_env": AppEnv.DEVELOPMENT, "public_base_url": "https://wi.example.com/"}
        )
        assert config.issuer == "https://wi.example.com"


class TestWithIntelligenceConfig:
    def test_defaults_to_the_hedge_fund_package(self) -> None:
        assert WithIntelligenceConfig().asset_class_groups == (AssetClassGroup.HFM,)

    def test_reads_packages_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WITH_INTELLIGENCE_ASSET_CLASS_GROUPS", '["hfm","sfo"]')
        assert WithIntelligenceConfig().asset_class_groups == (
            AssetClassGroup.HFM,
            AssetClassGroup.SFO,
        )

    def test_rejects_a_package_the_api_does_not_define(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WITH_INTELLIGENCE_ASSET_CLASS_GROUPS", '["crypto"]')
        with pytest.raises(ValidationError):
            WithIntelligenceConfig()

    def test_defaults_to_the_documented_base_url(self) -> None:
        assert WithIntelligenceConfig().base_url == "https://api.withintelligence.com"

    def test_rejects_an_http_api_url(self) -> None:
        with pytest.raises(ValidationError, match="HTTPS"):
            WithIntelligenceConfig(base_url="http://api.withintelligence.com")


class TestDatabaseConfig:
    def test_builds_a_dsn_from_discrete_fields(self) -> None:
        config = DatabaseConfig.model_validate(
            {"host": "db", "name": "wi", "user": "u", "password": "p", "port": 5433}
        )
        assert config.connection_url == "postgresql+asyncpg://u:p@db:5433/wi"

    def test_reports_which_fields_are_missing(self) -> None:
        with pytest.raises(ValidationError, match="DB_NAME"):
            DatabaseConfig.model_validate({"host": "db", "user": "u", "password": "p"})

    def test_accepts_database_url_as_an_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/wi")
        assert DatabaseConfig().connection_url == "postgresql+asyncpg://u:p@db:5432/wi"


class TestDatabaseConfigSslMode:
    def test_applies_the_chart_sslmode_when_the_url_has_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/wi")
        monkeypatch.setenv("PG_DATABASE_SSL_MODE", "verify")

        ssl_ctx = DatabaseConfig().connect_args.get("ssl")

        assert isinstance(ssl_ctx, ssl.SSLContext)
        assert ssl_ctx.verify_mode == ssl.CERT_REQUIRED
        assert ssl_ctx.check_hostname is True

    def test_prefers_the_url_sslmode_over_the_chart_sslmode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/wi?sslmode=disable")
        monkeypatch.setenv("PG_DATABASE_SSL_MODE", "verify")

        assert DatabaseConfig().connect_args == {"ssl": "disable"}

    def test_leaves_tls_to_the_driver_without_any_sslmode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/wi")
        monkeypatch.delenv("PG_DATABASE_SSL_MODE", raising=False)

        assert DatabaseConfig().connect_args == {}

    def test_applies_the_chart_sslmode_to_discrete_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PG_DATABASE_SSL_MODE", "verify-ca")

        config = DatabaseConfig.model_validate(
            {"host": "db", "name": "wi", "user": "u", "password": "p"}
        )

        ssl_ctx = config.connect_args.get("ssl")
        assert isinstance(ssl_ctx, ssl.SSLContext)
        assert ssl_ctx.verify_mode == ssl.CERT_REQUIRED
        assert ssl_ctx.check_hostname is False

    def test_rejects_an_unknown_chart_sslmode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/wi")
        monkeypatch.setenv("PG_DATABASE_SSL_MODE", "sideways")

        with pytest.raises(ValidationError, match="Unsupported sslmode"):
            DatabaseConfig()


class TestNormalizeAsyncpgUrl:
    def test_adds_the_asyncpg_driver(self) -> None:
        url, connect_args = normalize_asyncpg_url("postgresql://u:p@db:5432/wi")
        assert url == "postgresql+asyncpg://u:p@db:5432/wi"
        assert connect_args == {}

    def test_strips_sslmode_into_a_connect_arg(self) -> None:
        url, connect_args = normalize_asyncpg_url("postgresql://u:p@db:5432/wi?sslmode=verify-full")
        assert "sslmode" not in url
        assert "ssl" in connect_args

    def test_hands_sslmode_disable_to_the_driver(self) -> None:
        url, connect_args = normalize_asyncpg_url("postgresql://u:p@db:5432/wi?sslmode=disable")
        assert "sslmode" not in url
        assert connect_args == {"ssl": "disable"}

    def test_rejects_a_non_postgres_url(self) -> None:
        with pytest.raises(ValueError, match="PostgreSQL"):
            normalize_asyncpg_url("mysql://u:p@db/wi")

    def test_rejects_an_unknown_sslmode(self) -> None:
        with pytest.raises(ValueError, match="Unsupported sslmode"):
            normalize_asyncpg_url("postgresql://u:p@db/wi?sslmode=sideways")


class TestAuthConfig:
    def test_redirect_allowlist_defaults_to_the_supported_clients(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AUTH_ALLOWED_REDIRECT_HOSTS", raising=False)
        monkeypatch.delenv("AUTH_ALLOWED_REDIRECT_SCHEMES", raising=False)

        config = AuthConfig()

        assert config.allowed_redirect_hosts == DEFAULT_ALLOWED_REDIRECT_HOSTS
        assert config.allowed_redirect_schemes == ("cursor",)

    def test_redirect_allowlist_env_vars_replace_the_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTH_ALLOWED_REDIRECT_HOSTS", "claude.ai, mcp.example.com")
        monkeypatch.setenv("AUTH_ALLOWED_REDIRECT_SCHEMES", "")

        config = AuthConfig()

        assert config.allowed_redirect_hosts == ("claude.ai", "mcp.example.com")
        assert config.allowed_redirect_schemes == ()
