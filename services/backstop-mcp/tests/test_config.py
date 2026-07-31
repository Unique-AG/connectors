import ssl

import pytest

from backstop_mcp.config import DatabaseConfig, normalize_asyncpg_url


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
