import logging
from typing import cast

import structlog
from structlog.typing import Processor

from backstop_mcp.config import AppConfig, LogLevel

LOG_LEVEL_MAP: dict[LogLevel, int] = {
    LogLevel.FATAL: logging.CRITICAL,
    LogLevel.ERROR: logging.ERROR,
    LogLevel.WARN: logging.WARNING,
    LogLevel.INFO: logging.INFO,
    LogLevel.DEBUG: logging.DEBUG,
}


def configure_logging(config: AppConfig) -> None:
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="time"),
    ]
    runtime_processors: list[Processor] = []
    if config.app_env == "development":
        renderer: Processor = structlog.dev.ConsoleRenderer(colors=True, pad_level=False)
    else:
        runtime_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    level = LOG_LEVEL_MAP.get(config.log_level, logging.INFO)
    structlog.configure(
        processors=[*shared_processors, *runtime_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    logger = cast(structlog.typing.FilteringBoundLogger, structlog.get_logger())
    if name:
        logger = logger.bind(logger=name)
    return logger
