from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backstop_mcp.backstop_client import BackstopCredentialSecret
from backstop_mcp.db import BackstopCredential
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
    session: AsyncSession,
    user_id: str,
    credential: BackstopCredentialSecret,
    key: bytes,
    *,
    external_user_id: str | None = None,
    raw: dict[str, object] | None = None,
) -> str:
    """Encrypt and upsert a user's Backstop credential, keyed by username.

    Returns the durable `user_id` for this username. Concurrent first logins for the same
    username both propose a fresh id; `ON CONFLICT (backstop_username)` keeps a single row and
    returns whichever id won, so the unique index never surfaces as an unhandled error and both
    callers agree on the subject for the minted authorization code.

    `external_user_id` / `raw` are written when the login walk found the matching
    `system-users` record. Omitted fields are left as they are on conflict.

    Does not commit — the caller owns the transaction boundary (`db/engine.py::transaction`).
    """
    encrypted_blob = encrypt_credential(credential, key)
    values: dict[str, object] = {
        "user_id": user_id,
        "backstop_username": credential.username,
        "encrypted_blob": encrypted_blob,
    }
    conflict_set: dict[str, object] = {
        "encrypted_blob": encrypted_blob,
        "updated_at": func.now(),
    }
    if external_user_id is not None:
        values["external_user_id"] = external_user_id
        conflict_set["external_user_id"] = external_user_id
    if raw is not None:
        values["raw"] = raw
        conflict_set["raw"] = raw
    statement = (
        pg_insert(BackstopCredential)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[BackstopCredential.backstop_username],
            set_=conflict_set,
        )
        .returning(BackstopCredential.user_id)
    )
    result = await session.execute(statement)
    return result.scalar_one()


async def get_credential(
    session: AsyncSession, user_id: str, key: bytes
) -> BackstopCredentialSecret | None:
    """Fetch and decrypt a user's stored Backstop credential, or `None` if never connected."""
    row = await session.get(BackstopCredential, user_id)
    if row is None:
        return None
    return decrypt_credential(row.encrypted_blob, key)


async def get_system_user_cache(
    session: AsyncSession, user_id: str
) -> tuple[str, dict[str, object]] | None:
    """The Backstop system-user snapshot stored at login, or `None` if this row has none."""
    row = await session.get(BackstopCredential, user_id)
    if row is None or row.external_user_id is None or row.raw is None:
        return None
    return row.external_user_id, row.raw
