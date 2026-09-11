"""Config parsing, and the failures it turns into startup errors."""

import pytest
from pydantic import ValidationError

from with_intelligence_mcp.config import (
    AppConfig,
    AppEnv,
    AssetClassGroup,
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


class TestNormalizeAsyncpgUrl:
    def test_adds_the_asyncpg_driver(self) -> None:
        url, connect_args = normalize_asyncpg_url("postgresql://u:p@db:5432/wi")
        assert url == "postgresql+asyncpg://u:p@db:5432/wi"
        assert connect_args == {}

    def test_strips_sslmode_into_a_connect_arg(self) -> None:
        url, connect_args = normalize_asyncpg_url("postgresql://u:p@db:5432/wi?sslmode=verify-full")
        assert "sslmode" not in url
        assert "ssl" in connect_args

    def test_drops_sslmode_disable_entirely(self) -> None:
        url, connect_args = normalize_asyncpg_url("postgresql://u:p@db:5432/wi?sslmode=disable")
        assert "sslmode" not in url
        assert connect_args == {}

    def test_rejects_a_non_postgres_url(self) -> None:
        with pytest.raises(ValueError, match="PostgreSQL"):
            normalize_asyncpg_url("mysql://u:p@db/wi")

    def test_rejects_an_unknown_sslmode(self) -> None:
        with pytest.raises(ValueError, match="Unsupported sslmode"):
            normalize_asyncpg_url("postgresql://u:p@db/wi?sslmode=sideways")
