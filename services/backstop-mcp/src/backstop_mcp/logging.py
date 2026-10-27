"""Logging setup via `mcp_observability` (pino-json on stderr)."""

from mcp_observability import configure_logging as configure_pino_logging

from backstop_mcp.config import AppConfig


def configure_logging(config: AppConfig) -> None:
    configure_pino_logging(config.log_level.value.upper())
