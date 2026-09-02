from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from with_intelligence_mcp.db import WithIntelligenceSession
from with_intelligence_mcp.features.auth.crypto import decrypt_session, encrypt_session
from with_intelligence_mcp.with_intelligence_client import VendorSession


async def find_user_id_by_username(session: AsyncSession, username: str) -> str | None:
    """The durable `user_id` for a username, if that user has logged in before.

    So a returning user gets their existing id — and its tokens and history — instead of a
    fresh duplicate row.
    """
    result = await session.execute(
        select(WithIntelligenceSession.user_id).where(
            WithIntelligenceSession.wi_username == username
        )
    )
    return result.scalar_one_or_none()


async def save_session(
    session: AsyncSession,
    user_id: str,
    username: str,
    vendor_session: VendorSession,
    key: bytes,
) -> str:
    """Encrypt and upsert a user's vendor session, keyed by username. Returns the durable id.

    Concurrent first logins for the same username both propose a fresh id; `ON CONFLICT
    (wi_username)` keeps a single row and returns whichever won, so both callers agree on the
    subject. Does not commit — the caller owns the transaction boundary.
    """
    encrypted_blob = encrypt_session(vendor_session, key)
    statement = (
        pg_insert(WithIntelligenceSession)
        .values(user_id=user_id, wi_username=username, encrypted_blob=encrypted_blob)
        .on_conflict_do_update(
            index_elements=[WithIntelligenceSession.wi_username],
            set_={"encrypted_blob": encrypted_blob, "updated_at": func.now()},
        )
        .returning(WithIntelligenceSession.user_id)
    )
    result = await session.execute(statement)
    return result.scalar_one()


async def get_session(session: AsyncSession, user_id: str, key: bytes) -> VendorSession | None:
    """Fetch and decrypt a user's stored session, or `None` if they never connected."""
    row = await session.get(WithIntelligenceSession, user_id)
    if row is None:
        return None
    return decrypt_session(row.encrypted_blob, key)


async def lock_session(session: AsyncSession, user_id: str, key: bytes) -> VendorSession | None:
    """Read the row for update, so only one caller renews a rotating refresh token.

    `SELECT ... FOR UPDATE` rather than the in-memory lock alone: that lock is per process, and
    the chart scales this service horizontally. Two replicas renewing at once would each spend
    the same refresh token, and if the vendor rotates on refresh the loser's token is dead.
    """
    result = await session.execute(
        select(WithIntelligenceSession)
        .where(WithIntelligenceSession.user_id == user_id)
        .with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return decrypt_session(row.encrypted_blob, key)


async def replace_session(
    session: AsyncSession, user_id: str, vendor_session: VendorSession, key: bytes
) -> None:
    """Write a renewed session back over the locked row."""
    row = await session.get(WithIntelligenceSession, user_id)
    if row is None:
        return
    row.encrypted_blob = encrypt_session(vendor_session, key)
