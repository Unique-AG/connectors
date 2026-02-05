import logging

import structlog
from structlog.typing import Processor

from edgar_mcp.config import AppConfig

# Map pino log levels to Python logging levels
LOG_LEVEL_MAP = {
    "fatal": logging.CRITICAL,
    "error": logging.ERROR,
    "warn": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def configure_logging(config: AppConfig) -> None:
    """Configure structlog for JSON (production) or console (development) output."""
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="time"),
    ]

    if config.app_env == "development":
        renderer = structlog.dev.ConsoleRenderer(colors=True, pad_level=False)
    else:
        renderer = structlog.processors.JSONRenderer()

    level = LOG_LEVEL_MAP.get(config.log_level, logging.INFO)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,  # False for testing
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance, optionally with a bound name."""
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(logger=name)
    return logger
