import pytest


class TestDatabaseConfig:
    """Test database configuration URL building behavior."""

    def test_builds_url_from_individual_parts(self, monkeypatch):
        """When individual DB settings are provided, builds asyncpg URL."""
        monkeypatch.setenv("DB_HOST", "dbhost")
        monkeypatch.setenv("DB_PORT", "5433")
        monkeypatch.setenv("DB_NAME", "testdb")
        monkeypatch.setenv("DB_USER", "testuser")
        monkeypatch.setenv("DB_PASSWORD", "testpass")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()

        assert config.url == "postgresql+asyncpg://testuser:testpass@dbhost:5433/testdb"

    def test_uses_provided_url_directly(self, monkeypatch):
        """When DB_URL is provided, uses it directly."""
        monkeypatch.setenv("DB_URL", "postgresql+asyncpg://user:pass@host:5432/db")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()

        assert config.url == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_adds_asyncpg_driver_if_missing(self, monkeypatch):
        """When URL uses postgresql:// without driver, adds +asyncpg."""
        monkeypatch.setenv("DB_URL", "postgresql://user:pass@host:5432/db")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()

        assert config.url == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_raises_when_no_url_and_no_password(self, monkeypatch):
        """When neither URL nor password provided, raises error."""
        monkeypatch.delenv("DB_URL", raising=False)
        monkeypatch.delenv("DB_PASSWORD", raising=False)
        monkeypatch.delenv("DB_HOST", raising=False)
        monkeypatch.delenv("DB_NAME", raising=False)
        monkeypatch.delenv("DB_USER", raising=False)

        from edgar_mcp.config import DatabaseConfig

        with pytest.raises(ValueError, match="DB_URL not set; missing required fields:"):
            DatabaseConfig()

    def test_raises_when_partial_config(self, monkeypatch):
        """When only some individual parts provided, raises error."""
        monkeypatch.delenv("DB_URL", raising=False)
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_USER", "user")
        monkeypatch.delenv("DB_PASSWORD", raising=False)
        monkeypatch.delenv("DB_NAME", raising=False)

        from edgar_mcp.config import DatabaseConfig

        with pytest.raises(ValueError, match="DB_URL not set; missing required fields:"):
            DatabaseConfig()

    def test_url_encodes_special_characters(self, monkeypatch):
        """URL encoding handles special characters in password."""
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_USER", "user@domain")
        monkeypatch.setenv("DB_PASSWORD", "p@ss:w/rd")
        monkeypatch.setenv("DB_NAME", "testdb")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()
        assert "user%40domain" in config.url
        assert "p%40ss%3Aw%2Frd" in config.url

    def test_uses_default_port_when_not_specified(self, monkeypatch):
        """Default port 5432 is used when DB_PORT not set."""
        monkeypatch.setenv("DB_HOST", "dbhost")
        monkeypatch.delenv("DB_PORT", raising=False)
        monkeypatch.setenv("DB_NAME", "testdb")
        monkeypatch.setenv("DB_USER", "user")
        monkeypatch.setenv("DB_PASSWORD", "pass")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()

        assert ":5432/" in config.url

    def test_preserves_asyncpg_driver_if_already_present(self, monkeypatch):
        """URL with +asyncpg already present is not modified."""
        monkeypatch.setenv("DB_URL", "postgresql+asyncpg://user:pass@host:5432/db")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()

        assert config.url == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_raises_when_url_is_not_postgres(self, monkeypatch):
        """When DB_URL is not a PostgreSQL URL, raises error."""
        monkeypatch.setenv("DB_URL", "mysql://user:pass@host:3306/db")

        from edgar_mcp.config import DatabaseConfig

        with pytest.raises(ValueError, match="DB_URL must be a PostgreSQL connection string"):
            DatabaseConfig()

    def test_accepts_other_postgres_drivers(self, monkeypatch):
        """URLs with other PostgreSQL drivers like psycopg are accepted."""
        monkeypatch.setenv("DB_URL", "postgresql+psycopg://user:pass@host:5432/db")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()

        assert config.url == "postgresql+psycopg://user:pass@host:5432/db"
