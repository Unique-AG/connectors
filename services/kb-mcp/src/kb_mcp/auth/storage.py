"""Durable OAuth proxy storage — see auth/__init__.py:build_auth.

Every FastMCP-issued access token is a reference token, re-validated against
this store on every request, so losing it on a pod restart or across replicas
logs out every user. Settings._storage_must_be_durable already refuses to
boot without a durable config or an explicit ephemeral opt-in, so exactly one
of the two branches below is valid by the time this runs.
"""

import base64
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import FileTreeStore
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from kb_mcp.settings import Settings

_OAUTH_TABLE_NAME = "oauth_kv"


def _fernet_key_from_hex(hex_key: str) -> bytes:
    """ENCRYPTION_KEY is raw hex (openssl rand -hex 32); Fernet needs those
    same 32 bytes urlsafe-base64-encoded.
    """
    return base64.urlsafe_b64encode(bytes.fromhex(hex_key))


def build_storage(settings: Settings) -> AsyncKeyValue:
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
            fernet=Fernet(
                _fernet_key_from_hex(settings.encryption_key.get_secret_value())
            ),
            raise_on_decryption_error=False,
        )

    # Only reachable because the settings validator allowed it (dev opt-in).
    assert settings.allow_ephemeral_oauth_storage

    dev_dir = Path(tempfile.gettempdir()) / "kb-mcp-oauth-dev"
    return FernetEncryptionWrapper(
        key_value=FileTreeStore(data_directory=dev_dir),
        source_material="kb-mcp-local-dev-oauth-storage",
        salt="kb-mcp-local-dev",
        raise_on_decryption_error=False,
    )
