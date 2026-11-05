from mcp_configs import LoggingSettings
from mcp_observability import SecretRedaction
from mcp_observability import configure_logging as _configure_pino_logging
from sqlalchemy import make_url


def configure_logging(*, encryption_key: bytes, database_url: str) -> None:
    """The encryption key and the password of `database_url` are redacted from every line."""
    database_password = make_url(database_url).password
    secrets = (encryption_key.decode(), *([database_password] if database_password else []))
    _configure_pino_logging(
        LoggingSettings(),
        own_loggers=("with_intelligence_mcp",),
        redaction=SecretRedaction(secrets=secrets),
    )
