from unique_mcp.logging import configure_logging as configure_pino_logging

from with_intelligence_mcp.config import AppConfig


def configure_logging(config: AppConfig) -> None:
    configure_pino_logging(level=config.log_level.value.upper())
