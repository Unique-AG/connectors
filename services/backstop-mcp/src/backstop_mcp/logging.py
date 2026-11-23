"""Logging setup via `mcp_observability` (pino-json on stderr)."""

import hashlib
import hmac

from mcp_configs import LoggingSettings
from mcp_observability import SecretRedaction, configure_identifiable_values
from mcp_observability import configure_logging as configure_pino_logging
from sqlalchemy import make_url

# Versioned so the pseudonym key can be rotated without rotating the encryption key.
_PSEUDONYM_LABEL = b"backstop-mcp/log-pseudonyms/v1"


def configure_logging(
    settings: LoggingSettings, *, encryption_key: bytes, database_url: str
) -> None:
    """The encryption key and the password of `database_url` are redacted from every line."""
    database_password = make_url(database_url).password
    secrets = (encryption_key.decode(), *([database_password] if database_password else []))
    configure_pino_logging(
        settings, own_loggers=("backstop_mcp",), redaction=SecretRedaction(secrets=secrets)
    )
    configure_identifiable_values(settings, secret=_pseudonym_secret(encryption_key))


def _pseudonym_secret(encryption_key: bytes) -> bytes:
    """A key for pseudonyms alone, derived from the encryption key and never the key itself."""
    return hmac.new(encryption_key, _PSEUDONYM_LABEL, hashlib.sha256).digest()
