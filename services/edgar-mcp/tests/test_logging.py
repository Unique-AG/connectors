import io
import json
import sys
from typing import cast

import pytest


class TestLogging:
    """Test logging output format behavior."""

    def test_outputs_json_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """In production environment, logs output as NDJSON."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("LOG_LEVEL", "info")

        # Capture stdout
        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        from edgar_mcp.config import AppConfig
        from edgar_mcp.logging import configure_logging, get_logger

        configure_logging(AppConfig())
        logger = get_logger("test")
        logger.info("test message", extra_field="value")

        output = captured.getvalue()
        log_entry = cast(dict[str, str], json.loads(output.strip()))

        assert log_entry["level"] == "info"
        assert log_entry["event"] == "test message"
        assert log_entry["extra_field"] == "value"
        assert "time" in log_entry

    def test_outputs_readable_in_development(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """In development environment, logs are human-readable."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("LOG_LEVEL", "info")

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        from edgar_mcp.config import AppConfig
        from edgar_mcp.logging import configure_logging, get_logger

        configure_logging(AppConfig())
        logger = get_logger("test")
        logger.info("test message")

        output = captured.getvalue()

        # Should NOT be valid JSON (human readable format)
        with pytest.raises(json.JSONDecodeError):
            json.loads(output.strip())

        # Should contain the message
        assert "test message" in output

    def test_logger_binds_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_logger with name binds it to all log entries."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("LOG_LEVEL", "info")

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        from edgar_mcp.config import AppConfig
        from edgar_mcp.logging import configure_logging, get_logger

        configure_logging(AppConfig())
        logger = get_logger("my_component")
        logger.info("test")

        output = captured.getvalue()
        log_entry = cast(dict[str, str], json.loads(output.strip()))

        assert log_entry["logger"] == "my_component"

    def test_respects_log_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Log messages below configured level are filtered."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("LOG_LEVEL", "warn")

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        from edgar_mcp.config import AppConfig
        from edgar_mcp.logging import configure_logging, get_logger

        configure_logging(AppConfig())
        logger = get_logger("test")
        logger.info("info message")
        logger.warning("warning message")

        output = captured.getvalue().strip()
        # Should only have the warning message
        lines = [line for line in output.split("\n") if line]
        assert len(lines) == 1
        log_entry = cast(dict[str, str], json.loads(lines[0]))
        assert log_entry["event"] == "warning message"
        assert log_entry["level"] == "warning"

    def test_logger_without_name_has_no_logger_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_logger without name doesn't add logger key."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("LOG_LEVEL", "info")

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        from edgar_mcp.config import AppConfig
        from edgar_mcp.logging import configure_logging, get_logger

        configure_logging(AppConfig())
        logger = get_logger()
        logger.info("test")

        output = captured.getvalue()
        log_entry = cast(dict[str, str], json.loads(output.strip()))

        assert "logger" not in log_entry
