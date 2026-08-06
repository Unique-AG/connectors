"""Durable OAuth proxy storage — see auth/__init__.py:build_auth.

Every FastMCP-issued access token is a reference token: OAuthProxy re-validates
it against this store on every request (see the JTI-mapping lookup in
fastmcp.server.auth.oauth_proxy.proxy.OAuthProxy.load_access_token). Six
collections live here (client registrations, transactions, authorization
codes, upstream tokens, JTI mappings, refresh tokens); losing them on a pod
restart or across replicas logs out every user. Settings._storage_must_be_durable
already refuses to boot without either a real DATABASE_URL +
STORAGE_ENCRYPTION_KEY or an explicit ALLOW_EPHEMERAL_OAUTH_STORAGE opt-in, so
by the time build_storage runs, exactly one of the two branches below is valid.
"""

import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import FileTreeStore
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from kb_mcp.settings import Settings

_OAUTH_TABLE_NAME = "oauth_kv"


def build_storage(settings: Settings) -> AsyncKeyValue:
    """Durable, encrypted OAuth state. Fails closed — never silently ephemeral."""
    if settings.database_url and settings.storage_encryption_key:
        store = PostgreSQLStore(
            url=str(settings.database_url),
            table_name=_OAUTH_TABLE_NAME,
            auto_create=True,
        )
        return FernetEncryptionWrapper(
            key_value=store,
            fernet=Fernet(settings.storage_encryption_key.get_secret_value().encode()),
        )

    # Only reachable because the settings validator allowed it (dev opt-in).
    assert settings.allow_ephemeral_oauth_storage

    dev_dir = Path(tempfile.gettempdir()) / "kb-mcp-oauth-dev"
    return FernetEncryptionWrapper(
        key_value=FileTreeStore(data_directory=dev_dir),
        source_material="kb-mcp-local-dev-oauth-storage",
        salt="kb-mcp-local-dev",
    )
