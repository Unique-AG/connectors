"""Logging setup via `mcp_observability` (pino-json on stderr)."""

import hashlib
import hmac

from mcp_configs import LoggingSettings
from mcp_observability import configure_identifiable_values
from mcp_observability import configure_logging as configure_pino_logging

# Versioned so the pseudonym key can be rotated without rotating the encryption key.
_PSEUDONYM_LABEL = b"backstop-mcp/log-pseudonyms/v1"


def configure_logging(settings: LoggingSettings, *, encryption_key: bytes) -> None:
    configure_pino_logging(settings, own_loggers=("backstop_mcp",))
    configure_identifiable_values(settings, secret=_pseudonym_secret(encryption_key))


def _pseudonym_secret(encryption_key: bytes) -> bytes:
    """A key for pseudonyms alone, derived from the encryption key and never the key itself."""
    return hmac.new(encryption_key, _PSEUDONYM_LABEL, hashlib.sha256).digest()
