"""Logging setup via `mcp_observability` (pino-json on stderr)."""

import hashlib
import hmac
from urllib.parse import unquote, urlsplit

from mcp_configs import LoggingSettings
from mcp_observability import configure_identifiable_values
from mcp_observability import configure_logging as configure_pino_logging

from backstop_mcp.config import DatabaseConfig, EncryptionConfig

# Versioned so the pseudonym key can be rotated without rotating the encryption key.
_PSEUDONYM_LABEL = b"backstop-mcp/log-pseudonyms/v1"


def configure_logging(
    settings: LoggingSettings, *, encryption_key: bytes, secrets: tuple[str, ...] = ()
) -> None:
    """`secrets` are redacted from every line, on top of the default secret patterns."""
    configure_pino_logging(settings, own_loggers=("backstop_mcp",), secrets=secrets)
    configure_identifiable_values(settings, secret=_pseudonym_secret(encryption_key))


def deployment_secrets(encryption: EncryptionConfig, database: DatabaseConfig) -> tuple[str, ...]:
    """The secrets this deployment is configured with: the encryption key and database password."""
    database_password = (
        unquote(urlsplit(str(database.url)).password or "")
        if database.url is not None
        else database.password
    )
    encryption_key = encryption.encryption_key
    return tuple(
        secret
        for secret in (
            encryption_key.get_secret_value() if encryption_key is not None else None,
            database_password,
        )
        if secret
    )


def _pseudonym_secret(encryption_key: bytes) -> bytes:
    """A key for pseudonyms alone, derived from the encryption key and never the key itself."""
    return hmac.new(encryption_key, _PSEUDONYM_LABEL, hashlib.sha256).digest()
