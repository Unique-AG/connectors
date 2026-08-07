"""Persistence for the custom-field schema snapshot. Serialization lives in `snapshot.py`."""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backstop_mcp.db import CustomFieldSchemaSnapshot
from backstop_mcp.features.custom_fields.snapshot import (
    StoredSnapshot,
    dump_definitions,
    load_definitions,
)
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition


async def load_snapshot(
    session: AsyncSession, base_url: str, subject: str
) -> StoredSnapshot | None:
    """Read the snapshot for `(base_url, subject)`, or None if absent or an older shape."""
    row = await session.get(CustomFieldSchemaSnapshot, (base_url, subject))
    if row is None:
        return None
    definitions = load_definitions(row.payload)
    if definitions is None:
        return None
    return StoredSnapshot(definitions=definitions, fetched_at=row.fetched_at)


async def save_snapshot(
    session: AsyncSession,
    base_url: str,
    subject: str,
    definitions: list[CustomFieldDefinition],
    fetched_at: datetime,
) -> None:
    """Upsert the snapshot for `(base_url, subject)`, stamped with the caller's fetch time.

    `fetched_at` is passed in rather than read from the clock here so the caller that also
    tracks freshness in memory stamps both from a single reading.

    A single `ON CONFLICT DO UPDATE` rather than read-then-insert-or-update: concurrent
    refreshes for the same subject race to write the same row, and the read-first form lets
    both see no row and both INSERT, failing one on the primary key. Last writer wins — they
    fetched under the same credentials.
    """
    payload: object = dump_definitions(definitions)
    statement = pg_insert(CustomFieldSchemaSnapshot).values(
        base_url=base_url, subject=subject, payload=payload, fetched_at=fetched_at
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[
                CustomFieldSchemaSnapshot.base_url,
                CustomFieldSchemaSnapshot.subject,
            ],
            set_={"payload": payload, "fetched_at": fetched_at, "updated_at": func.now()},
        )
    )
