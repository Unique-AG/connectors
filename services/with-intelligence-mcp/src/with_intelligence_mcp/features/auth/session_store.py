import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from with_intelligence_mcp.db import WithIntelligenceSession
from with_intelligence_mcp.features.auth.crypto import decrypt_session, encrypt_session
from with_intelligence_mcp.with_intelligence_client import WiSession


@dataclass(frozen=True)
class SessionRefreshClaim:
    stored_session: WiSession | None
    acquired: bool


async def find_subject_by_username(session: AsyncSession, username: str) -> str | None:
    """Return the durable user ID for a known username."""
    result = await session.execute(
        select(WithIntelligenceSession.user_id).where(
            WithIntelligenceSession.wi_username == username
        )
    )
    return result.scalar_one_or_none()


async def upsert_stored_wi_session(
    session: AsyncSession,
    subject: str,
    username: str,
    wi_session: WiSession,
    key: bytes,
) -> str:
    """Encrypt and upsert a WI session by username."""
    encrypted_blob = encrypt_session(wi_session, key)
    statement = (
        pg_insert(WithIntelligenceSession)
        .values(user_id=subject, wi_username=username, encrypted_blob=encrypted_blob)
        .on_conflict_do_update(
            index_elements=[WithIntelligenceSession.wi_username],
            set_={
                "encrypted_blob": encrypted_blob,
                "refresh_claim_id": None,
                "refresh_claimed_at": None,
                "updated_at": func.now(),
            },
        )
        .returning(WithIntelligenceSession.user_id)
    )
    result = await session.execute(statement)
    return result.scalar_one()


async def get_stored_wi_session(
    session: AsyncSession, subject: str, key: bytes
) -> WiSession | None:
    """Fetch and decrypt a user's stored session, or `None` if they never connected."""
    row = await session.get(WithIntelligenceSession, subject)
    if row is None:
        return None
    return decrypt_session(row.encrypted_blob, key)


async def claim_session_refresh(
    session: AsyncSession,
    subject: str,
    key: bytes,
    claim_id: uuid.UUID,
    claim_expired_before: datetime,
) -> SessionRefreshClaim:
    result = await session.execute(
        select(WithIntelligenceSession)
        .where(WithIntelligenceSession.user_id == subject)
        .with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        return SessionRefreshClaim(stored_session=None, acquired=False)
    stored = decrypt_session(row.encrypted_blob, key)
    if (
        row.refresh_claim_id is not None
        and row.refresh_claimed_at is not None
        and row.refresh_claimed_at >= claim_expired_before
    ):
        return SessionRefreshClaim(stored_session=stored, acquired=False)
    row.refresh_claim_id = claim_id
    row.refresh_claimed_at = func.now()
    return SessionRefreshClaim(stored_session=stored, acquired=True)


async def release_session_refresh(session: AsyncSession, subject: str, claim_id: uuid.UUID) -> bool:
    result = await session.execute(
        update(WithIntelligenceSession)
        .where(
            WithIntelligenceSession.user_id == subject,
            WithIntelligenceSession.refresh_claim_id == claim_id,
        )
        .values(refresh_claim_id=None, refresh_claimed_at=None)
        .returning(WithIntelligenceSession.user_id)
    )
    return result.scalar_one_or_none() is not None


async def complete_session_refresh(
    session: AsyncSession,
    subject: str,
    wi_session: WiSession,
    key: bytes,
    claim_id: uuid.UUID,
) -> bool:
    result = await session.execute(
        update(WithIntelligenceSession)
        .where(
            WithIntelligenceSession.user_id == subject,
            WithIntelligenceSession.refresh_claim_id == claim_id,
        )
        .values(
            encrypted_blob=encrypt_session(wi_session, key),
            refresh_claim_id=None,
            refresh_claimed_at=None,
            updated_at=func.now(),
        )
        .returning(WithIntelligenceSession.user_id)
    )
    return result.scalar_one_or_none() is not None
