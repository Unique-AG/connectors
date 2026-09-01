from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from with_intelligence_mcp.db import WithIntelligenceCredential
from with_intelligence_mcp.features.auth.crypto import decrypt_credential, encrypt_credential
from with_intelligence_mcp.with_intelligence_client import VendorCredential


async def find_user_id_by_username(session: AsyncSession, username: str) -> str | None:
    """The durable `user_id` for a username, if that user has logged in before.

    So a returning user reconnecting gets their existing id — and its tokens and history —
    instead of a fresh duplicate row.
    """
    result = await session.execute(
        select(WithIntelligenceCredential.user_id).where(
            WithIntelligenceCredential.wi_username == username
        )
    )
    return result.scalar_one_or_none()


async def save_credential(
    session: AsyncSession, user_id: str, credential: VendorCredential, key: bytes
) -> str:
    """Encrypt and upsert a user's credential, keyed by username. Returns the durable `user_id`.

    Concurrent first logins for the same username both propose a fresh id; `ON CONFLICT
    (wi_username)` keeps a single row and returns whichever won, so the unique index never
    surfaces as an unhandled error and both callers agree on the subject.

    Does not commit — the caller owns the transaction boundary.
    """
    encrypted_blob = encrypt_credential(credential, key)
    statement = (
        pg_insert(WithIntelligenceCredential)
        .values(
            user_id=user_id,
            wi_username=credential.username,
            encrypted_blob=encrypted_blob,
        )
        .on_conflict_do_update(
            index_elements=[WithIntelligenceCredential.wi_username],
            set_={"encrypted_blob": encrypted_blob, "updated_at": func.now()},
        )
        .returning(WithIntelligenceCredential.user_id)
    )
    result = await session.execute(statement)
    return result.scalar_one()


async def get_credential(
    session: AsyncSession, user_id: str, key: bytes
) -> VendorCredential | None:
    """Fetch and decrypt a user's stored credential, or `None` if never connected."""
    row = await session.get(WithIntelligenceCredential, user_id)
    if row is None:
        return None
    return decrypt_credential(row.encrypted_blob, key)
