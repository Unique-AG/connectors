from __future__ import annotations

from cryptography.fernet import Fernet
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.stores.redis import RedisStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from q_bridge_mcp.config.settings import Environment, settings


def create_storage() -> AsyncKeyValue:
    if settings.python_env is Environment.PRODUCTION:
        return _create_redis_storage()

    return _create_file_storage()


def _create_file_storage() -> AsyncKeyValue:
    storage_directory = settings.storage_path.expanduser()
    data_directory = storage_directory / "data"
    metadata_directory = storage_directory / "metadata"
    data_directory.mkdir(parents=True, exist_ok=True)
    metadata_directory.mkdir(parents=True, exist_ok=True)

    store = FileTreeStore(
        data_directory=data_directory,
        metadata_directory=metadata_directory,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(data_directory),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
            data_directory
        ),
    )
    return _encrypt_storage(store)


def _create_redis_storage() -> AsyncKeyValue:
    if not settings.redis_host:
        raise ValueError("REDIS_HOST is required when PYTHON_ENV=production")

    store = RedisStore(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_database,
        password=(
            settings.redis_password.get_secret_value()
            if settings.redis_password is not None
            else None
        ),
        ssl=settings.redis_ssl,
    )
    return _encrypt_storage(store)


def _encrypt_storage(store: AsyncKeyValue) -> AsyncKeyValue:
    encryption_key = settings.storage_encryption_key.get_secret_value().encode()
    return FernetEncryptionWrapper(key_value=store, fernet=Fernet(encryption_key))
