"""main() redacts every configured secret and every caller's token from the logs."""

import json
import logging
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from mcp_observability import (
    RedactRequestSecretsMiddleware,
    RedactToolCallSecretsMiddleware,
)

from kb_mcp.main import main

_JWT_SIGNING_KEY = "jwt-signing-key-0123"
_ENCRYPTION_KEY = "0f" * 32
_UNIQUE_APP_KEY = "unique-app-key-0123"


@pytest.fixture(autouse=True)
def root_handlers() -> Iterator[None]:
    root = logging.getLogger()
    handlers = list(root.handlers)
    root.handlers = []
    yield
    root.handlers = handlers


def _run_main() -> MagicMock:
    with (
        patch("kb_mcp.main.ENV_FILE", None),
        patch("kb_mcp.main.configure_tracing"),
        patch("kb_mcp.main.start_memory_trimmer"),
        patch("kb_mcp.main.install_pooled_http_client"),
        patch("kb_mcp.main.build_auth", return_value=MagicMock()),
        patch("kb_mcp.main.FastMCP") as mock_fastmcp,
        patch("kb_mcp.main.setup_ops", return_value=MagicMock()),
    ):
        main()
    return mock_fastmcp


def _test_message(capsys: pytest.CaptureFixture[str]) -> str:
    lines = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    (line,) = [line for line in lines if line["context"] == "kb_mcp.tests"]
    return line["msg"]


def test_redacts_the_keys_and_the_decoded_database_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ZITADEL_JWT_SIGNING_KEY", _JWT_SIGNING_KEY)
    monkeypatch.setenv("ENCRYPTION_KEY", _ENCRYPTION_KEY)
    monkeypatch.setenv("UNIQUE_APP_KEY", _UNIQUE_APP_KEY)
    monkeypatch.setenv("DATABASE_URL", "postgresql://kb:db%2Fpassword-1@db:5432/kb")
    monkeypatch.setenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", "false")

    _run_main()
    logging.getLogger("kb_mcp.tests").warning(
        "secrets %s %s %s db/password-1",
        _JWT_SIGNING_KEY,
        _ENCRYPTION_KEY,
        _UNIQUE_APP_KEY,
    )

    assert (
        _test_message(capsys) == "secrets [Redacted] [Redacted] [Redacted] [Redacted]"
    )


def test_redacts_a_database_password_given_in_the_query_string(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ZITADEL_JWT_SIGNING_KEY", _JWT_SIGNING_KEY)
    monkeypatch.setenv("ENCRYPTION_KEY", _ENCRYPTION_KEY)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://kb@db:5432/kb?password=db%2Fpassword-2&sslmode=require",
    )
    monkeypatch.setenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", "false")

    _run_main()
    logging.getLogger("kb_mcp.tests").warning("connecting with db/password-2")

    assert _test_message(capsys) == "connecting with [Redacted]"


def test_redacts_the_signing_key_with_ephemeral_storage_and_no_app_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ZITADEL_JWT_SIGNING_KEY", _JWT_SIGNING_KEY)
    monkeypatch.delenv("UNIQUE_APP_KEY", raising=False)

    _run_main()
    logging.getLogger("kb_mcp.tests").warning("signed with %s", _JWT_SIGNING_KEY)

    assert _test_message(capsys) == "signed with [Redacted]"


def test_redacts_the_callers_token_around_every_request_and_tool_call() -> None:
    mock_fastmcp = _run_main()

    (first_tool_middleware, *_) = mock_fastmcp.call_args.kwargs["middleware"]
    run = mock_fastmcp.return_value.run
    (first_http_middleware, *_) = run.call_args.kwargs["middleware"]
    assert isinstance(first_tool_middleware, RedactToolCallSecretsMiddleware)
    assert first_http_middleware.cls is RedactRequestSecretsMiddleware
