"""Logging setup via `unique_mcp.logging` (pino-json on stderr)."""

from unique_mcp.logging import configure_logging as configure_pino_logging

from backstop_mcp.config import AppConfig
from backstop_mcp.observability import install_log_handlers


def configure_logging(config: AppConfig) -> None:
    configure_pino_logging(level=config.log_level.value.upper())
    install_log_handlers()
