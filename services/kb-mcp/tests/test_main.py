"""main() must still load .env into the process env.

kb_mcp.settings.Settings only feeds its own fields from .env — it doesn't
touch os.environ. configure_logging (LOG_LEVEL), configure_tracing (OTEL_*),
and unique_toolkit's settings (UNIQUE_APP_*, which look for a file named
unique.env, not .env) all read raw process env directly, so main() has to
populate it too, or their .env values silently stop applying.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from kb_mcp.main import main

pytestmark = pytest.mark.ai


def test_env_file_reaches_process_env_for_non_settings_consumers(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LOG_LEVEL=debug\nOTEL_TRACES_EXPORTER=console\nUNIQUE_APP_KEY=test-key\n"
    )
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
    monkeypatch.delenv("UNIQUE_APP_KEY", raising=False)
    monkeypatch.setattr("kb_mcp.main.ENV_FILE", env_file)

    with (
        patch("kb_mcp.main.configure_tracing"),
        patch("kb_mcp.main.configure_logging"),
        patch("kb_mcp.main.build_auth", return_value=MagicMock()),
        patch("kb_mcp.main.FastMCP") as mock_fastmcp,
        patch("kb_mcp.main.setup_ops", return_value=MagicMock()),
    ):
        mock_fastmcp.return_value.run = MagicMock()
        main()

    assert os.environ["LOG_LEVEL"] == "debug"
    assert os.environ["OTEL_TRACES_EXPORTER"] == "console"
    assert os.environ["UNIQUE_APP_KEY"] == "test-key"


def test_no_env_file_resolved_skips_load_dotenv_entirely(monkeypatch):
    """load_dotenv(None) falls back to its own find_dotenv() search and could
    load an unrelated .env (e.g. a monorepo root file) — when Settings
    resolved no file, main() must not call load_dotenv at all."""
    monkeypatch.setattr("kb_mcp.main.ENV_FILE", None)

    with (
        patch("kb_mcp.main.load_dotenv") as mock_load_dotenv,
        patch("kb_mcp.main.configure_tracing"),
        patch("kb_mcp.main.configure_logging"),
        patch("kb_mcp.main.build_auth", return_value=MagicMock()),
        patch("kb_mcp.main.FastMCP") as mock_fastmcp,
        patch("kb_mcp.main.setup_ops", return_value=MagicMock()),
    ):
        mock_fastmcp.return_value.run = MagicMock()
        main()

    mock_load_dotenv.assert_not_called()
