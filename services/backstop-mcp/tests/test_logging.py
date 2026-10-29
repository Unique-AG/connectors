import hashlib
import hmac
import json
import logging

import pytest
from mcp_configs import LoggingSettings, LogLevel
from mcp_observability import identifiable_value
from pydantic import PostgresDsn, SecretStr

from backstop_mcp.config import DatabaseConfig, EncryptionConfig
from backstop_mcp.logging import configure_logging, deployment_secrets

_ENCRYPTION_KEY = b"encryption-key-material"
_LOGIN = "jdoe"


def _keyed(value: str, key: bytes) -> str:
    return f"hmac-sha256:{hmac.new(key, value.encode(), hashlib.sha256).hexdigest()}"


class TestPseudonymSecret:
    def test_keys_pseudonyms_with_a_secret_derived_from_the_encryption_key(self) -> None:
        derived = hmac.new(
            _ENCRYPTION_KEY, b"backstop-mcp/log-pseudonyms/v1", hashlib.sha256
        ).digest()

        configure_logging(LoggingSettings(log_level=LogLevel.INFO), encryption_key=_ENCRYPTION_KEY)

        assert str(identifiable_value(_LOGIN)) == _keyed(_LOGIN, derived)

    def test_never_keys_pseudonyms_with_the_encryption_key_itself(self) -> None:
        configure_logging(LoggingSettings(log_level=LogLevel.INFO), encryption_key=_ENCRYPTION_KEY)

        assert str(identifiable_value(_LOGIN)) != _keyed(_LOGIN, _ENCRYPTION_KEY)


class TestDeploymentSecrets:
    def test_reads_the_encryption_key_and_the_password_of_a_database_url(self) -> None:
        secrets = deployment_secrets(
            EncryptionConfig(encryption_key=SecretStr("encryption-key-value")),
            DatabaseConfig(url=PostgresDsn("postgresql://app:db%2Fpassword-1@db:5432/backstop")),
        )

        assert secrets == ("encryption-key-value", "db/password-1")

    def test_reads_the_password_of_discrete_database_fields(self) -> None:
        secrets = deployment_secrets(
            EncryptionConfig(encryption_key=SecretStr("encryption-key-value")),
            DatabaseConfig(host="db", name="backstop", user="app", password="db-password-1"),
        )

        assert secrets == ("encryption-key-value", "db-password-1")

    def test_redacts_them_from_every_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        root = logging.getLogger()
        handlers = list(root.handlers)
        root.handlers = []
        try:
            configure_logging(
                LoggingSettings(log_level=LogLevel.INFO),
                encryption_key=_ENCRYPTION_KEY,
                secrets=("db-password-1",),
            )
            logging.getLogger("backstop_mcp.tests").warning("connect failed with db-password-1")
        finally:
            root.handlers = handlers

        (line,) = capsys.readouterr().err.splitlines()
        assert json.loads(line)["msg"] == "connect failed with [Redacted]"
