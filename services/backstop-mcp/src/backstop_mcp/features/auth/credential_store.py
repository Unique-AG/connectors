from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backstop_mcp.backstop_client.credential import BackstopCredentialSecret
from backstop_mcp.db.models import BackstopCredential
from backstop_mcp.features.auth.crypto import decrypt_credential, encrypt_credential


async def find_user_id_by_username(session: AsyncSession, username: str) -> str | None:
    """Look up the durable `user_id` for a Backstop username, if that user has logged in before.

    Used so a returning user reconnecting through the login form gets their existing
    `user_id` (and its associated OAuth tokens/history) instead of a fresh duplicate row.
    """
    result = await session.execute(
        select(BackstopCredential.user_id).where(BackstopCredential.backstop_username == username)
    )
    return result.scalar_one_or_none()


async def save_credential(
    session: AsyncSession, user_id: str, credential: BackstopCredentialSecret, key: bytes
) -> None:
    """Encrypt and upsert a user's Backstop credential.

    Does not commit — the caller owns the transaction boundary (`db/engine.py::transaction`).
    """
    encrypted_blob = encrypt_credential(credential, key)
    existing = await session.get(BackstopCredential, user_id)
    if existing is not None:
        existing.backstop_username = credential.username
        existing.encrypted_blob = encrypted_blob
    else:
        session.add(
            BackstopCredential(
                user_id=user_id,
                backstop_username=credential.username,
                encrypted_blob=encrypted_blob,
            )
        )


async def get_credential(
    session: AsyncSession, user_id: str, key: bytes
) -> BackstopCredentialSecret | None:
    """Fetch and decrypt a user's stored Backstop credential, or `None` if never connected."""
    row = await session.get(BackstopCredential, user_id)
    if row is None:
        return None
    return decrypt_credential(row.encrypted_blob, key)
