"""Durable OAuth proxy storage — see auth/__init__.py:build_auth.

Every FastMCP-issued access token is a reference token, re-validated against
this store on every request, so losing it on a pod restart or across replicas
logs out every user. AuthSettings._storage_must_be_durable already refuses to
boot without a durable config or an explicit ephemeral opt-in, so exactly one
of the two branches below is valid by the time this runs.
"""

import base64
from pathlib import Path
import tempfile

from cryptography.fernet import Fernet
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import FileTreeStore
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from space_config_mcp.mcp.auth.settings import AuthSettings

_OAUTH_TABLE_NAME = "oauth_kv"


def _fernet_key_from_hex(hex_key: str) -> bytes:
    """ENCRYPTION_KEY is raw hex (openssl rand -hex 32); Fernet needs those
    same 32 bytes urlsafe-base64-encoded.
    """
    return base64.urlsafe_b64encode(bytes.fromhex(hex_key))


def build_storage(settings: AuthSettings) -> AsyncKeyValue:
    """Durable, encrypted OAuth state. Fails closed — never silently ephemeral."""
    if settings.database_url and settings.encryption_key:
        store = PostgreSQLStore(
            url=str(settings.database_url),
            table_name=_OAUTH_TABLE_NAME,
            auto_create=True,
        )
        # Decryption failure = cache miss, so key rotation costs one re-login.
        return FernetEncryptionWrapper(
            key_value=store,
            fernet=Fernet(_fernet_key_from_hex(settings.encryption_key.get_secret_value())),
            raise_on_decryption_error=False,
        )

    # Only reachable because the settings validator allowed it (dev opt-in).
    if not settings.allow_ephemeral_oauth_storage:
        raise RuntimeError(
            "OAuth storage is not configured: set DATABASE_URL + ENCRYPTION_KEY, "
            "or ALLOW_EPHEMERAL_OAUTH_STORAGE=true for local dev."
        )

    dev_dir = Path(tempfile.mkdtemp(prefix="space-config-mcp-oauth-"))
    return FernetEncryptionWrapper(
        key_value=FileTreeStore(data_directory=dev_dir),
        source_material="space-config-mcp-local-dev-oauth-storage",
        salt="space-config-mcp-local-dev",
        raise_on_decryption_error=False,
    )
