import hashlib
import hmac
import json
import logging
from collections.abc import Iterator

import pytest
from mcp_configs import LoggingSettings, LogLevel
from mcp_observability import identifiable_value

from backstop_mcp.logging import configure_logging

_ENCRYPTION_KEY = b"encryption-key-material"
_LOGIN = "jdoe"
_DATABASE_URL = "postgresql+asyncpg://app:db-password-1@db:5432/backstop"


def _keyed(value: str, key: bytes) -> str:
    return f"hmac-sha256:{hmac.new(key, value.encode(), hashlib.sha256).hexdigest()}"


class TestPseudonymSecret:
    def test_keys_pseudonyms_with_a_secret_derived_from_the_encryption_key(self) -> None:
        derived = hmac.new(
            _ENCRYPTION_KEY, b"backstop-mcp/log-pseudonyms/v1", hashlib.sha256
        ).digest()

        configure_logging(
            LoggingSettings(log_level=LogLevel.INFO),
            encryption_key=_ENCRYPTION_KEY,
            database_url=_DATABASE_URL,
        )

        assert str(identifiable_value(_LOGIN)) == _keyed(_LOGIN, derived)

    def test_never_keys_pseudonyms_with_the_encryption_key_itself(self) -> None:
        configure_logging(
            LoggingSettings(log_level=LogLevel.INFO),
            encryption_key=_ENCRYPTION_KEY,
            database_url=_DATABASE_URL,
        )

        assert str(identifiable_value(_LOGIN)) != _keyed(_LOGIN, _ENCRYPTION_KEY)


class TestRedaction:
    @pytest.fixture(autouse=True)
    def root_handlers(self) -> Iterator[None]:
        root = logging.getLogger()
        handlers = list(root.handlers)
        root.handlers = []
        yield
        root.handlers = handlers

    def test_redacts_the_encryption_key_and_the_decoded_database_password(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(
            LoggingSettings(log_level=LogLevel.INFO),
            encryption_key=_ENCRYPTION_KEY,
            database_url="postgresql+asyncpg://app:db%2Fpassword-1@db:5432/backstop",
        )

        logging.getLogger("backstop_mcp.tests").warning(
            "connect failed with db/password-1 and %s", _ENCRYPTION_KEY.decode()
        )

        (line,) = capsys.readouterr().err.splitlines()
        assert json.loads(line)["msg"] == "connect failed with [Redacted] and [Redacted]"

    def test_accepts_a_database_url_without_a_password(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(
            LoggingSettings(log_level=LogLevel.INFO),
            encryption_key=_ENCRYPTION_KEY,
            database_url="postgresql+asyncpg://app@db:5432/backstop",
        )

        logging.getLogger("backstop_mcp.tests").warning("connected as app")

        (line,) = capsys.readouterr().err.splitlines()
        assert json.loads(line)["msg"] == "connected as app"
