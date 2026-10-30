from mcp_configs import LoggingSettings
from mcp_observability import configure_logging as _configure_pino_logging


def configure_logging() -> None:
    _configure_pino_logging(LoggingSettings(), own_loggers=("with_intelligence_mcp",))
