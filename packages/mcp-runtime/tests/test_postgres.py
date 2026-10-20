import ssl
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from mcp_runtime import PostgresSettings, SslMode

CNPG_URL = "postgresql://dummy-user:dummy-password@cluster-rw.db.svc:5432/app"


def test_reads_the_url_the_base_chart_injects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", CNPG_URL)

    settings = PostgresSettings()

    assert (
        settings.connection_url
        == "postgresql+asyncpg://dummy-user:dummy-password@cluster-rw.db.svc:5432/app"
    )


def test_db_url_wins_over_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", CNPG_URL)
    monkeypatch.setenv(
        "DB_URL", "postgresql://dummy-other-user:dummy-other-password@other-host/other"
    )

    assert "other-host" in PostgresSettings().connection_url


def test_reads_database_url_from_a_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"DATABASE_URL={CNPG_URL}\n")

    assert PostgresSettings().url is not None


def test_builds_the_url_from_discrete_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "DB_HOST": "db",
        "DB_NAME": "app",
        "DB_USER": "dummy-user",
        "DB_PASSWORD": "dummy@pass/word",
    }.items():
        monkeypatch.setenv(name, value)

    assert (
        PostgresSettings().connection_url
        == "postgresql+asyncpg://dummy-user:dummy%40pass%2Fword@db:5432/app"
    )


def test_names_the_missing_fields_without_a_url() -> None:
    with pytest.raises(ValidationError, match="missing required fields: DB_HOST, DB_NAME"):
        PostgresSettings(user="dummy-user", password=SecretStr("dummy-password"))


def test_rejects_a_url_that_is_not_postgres() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL connection string"):
        PostgresSettings(url=SecretStr("mysql://dummy-user:dummy-password@db/app"))


def test_rejects_an_unknown_sslmode_in_the_url() -> None:
    with pytest.raises(ValidationError, match="Unsupported sslmode=sometimes"):
        PostgresSettings(url=SecretStr(f"{CNPG_URL}?sslmode=sometimes"))


def test_moves_sslmode_from_the_url_into_connect_args() -> None:
    url = f"{CNPG_URL}?sslmode=require&channel_binding=prefer&application_name=mcp"

    settings = PostgresSettings(url=SecretStr(url))

    assert settings.connection_url.endswith("/app?application_name=mcp")
    context = settings.connect_args.get("ssl")
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_NONE


def test_uses_the_chart_sslmode_when_the_url_has_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", CNPG_URL)
    monkeypatch.setenv("PG_DATABASE_SSL_MODE", "verify")

    context = PostgresSettings().connect_args.get("ssl")

    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_the_url_sslmode_wins_over_the_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"{CNPG_URL}?sslmode=disable")
    monkeypatch.setenv("PG_DATABASE_SSL_MODE", "verify")

    assert PostgresSettings().connect_args == {"ssl": "disable"}


@pytest.mark.parametrize("ssl_mode", ["disable", "allow", "prefer"])
def test_passes_a_mode_that_may_skip_tls_to_asyncpg_by_name(ssl_mode: SslMode) -> None:
    settings = PostgresSettings(url=SecretStr(CNPG_URL), ssl_mode=ssl_mode)

    assert settings.connect_args == {"ssl": ssl_mode}


def test_verify_ca_checks_the_certificate_but_not_the_host() -> None:
    settings = PostgresSettings(url=SecretStr(CNPG_URL), ssl_mode="verify-ca")

    context = settings.connect_args.get("ssl")

    assert isinstance(context, ssl.SSLContext)
    assert not context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_without_an_sslmode_asyncpg_decides() -> None:
    assert PostgresSettings(url=SecretStr(CNPG_URL)).connect_args == {}


def test_a_missing_ca_file_falls_back_to_the_system_trust_store(tmp_path: Path) -> None:
    settings = PostgresSettings(
        url=SecretStr(CNPG_URL),
        ssl_mode="verify-full",
        ssl_root_cert=tmp_path / "absent.crt",
    )

    assert isinstance(settings.connect_args.get("ssl"), ssl.SSLContext)


def test_keeps_the_password_out_of_its_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", CNPG_URL)

    assert "dummy-password" not in repr(PostgresSettings())


def test_pool_defaults_match_backstop() -> None:
    settings = PostgresSettings(url=SecretStr(CNPG_URL))

    assert (settings.pool_size, settings.max_overflow) == (5, 10)
