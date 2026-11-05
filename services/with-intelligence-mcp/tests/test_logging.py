import json
import logging
from collections.abc import Iterator

import pytest

from with_intelligence_mcp.logging import configure_logging

_ENCRYPTION_KEY = b"encryption-key-material"


@pytest.fixture(autouse=True)
def root_handlers() -> Iterator[None]:
    root = logging.getLogger()
    handlers = list(root.handlers)
    root.handlers = []
    yield
    root.handlers = handlers


class TestRedaction:
    def test_redacts_the_encryption_key_and_the_decoded_database_password(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(
            encryption_key=_ENCRYPTION_KEY,
            database_url="postgresql+asyncpg://app:db%2Fpassword-1@db:5432/wi",
        )

        logging.getLogger("with_intelligence_mcp.tests").warning(
            "connect failed with db/password-1 and %s", _ENCRYPTION_KEY.decode()
        )

        (line,) = capsys.readouterr().err.splitlines()
        assert json.loads(line)["msg"] == "connect failed with [Redacted] and [Redacted]"

    def test_accepts_a_database_url_without_a_password(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(
            encryption_key=_ENCRYPTION_KEY,
            database_url="postgresql+asyncpg://app@db:5432/wi",
        )

        logging.getLogger("with_intelligence_mcp.tests").warning("connected as app")

        (line,) = capsys.readouterr().err.splitlines()
        assert json.loads(line)["msg"] == "connected as app"
