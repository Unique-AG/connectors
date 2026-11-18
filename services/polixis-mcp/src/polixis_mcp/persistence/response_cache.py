"""The cache of Polixis's answers, in a table of its own rather than the key-value store, so that
each answer can carry its size and when it was last read, and the cull can keep the cache under
a size by deleting the least recently used ones. A migration makes the table.
"""

from datetime import timedelta
import logging
from typing import Protocol, runtime_checkable

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from polixis_mcp.persistence.models import ResponseCacheRow
from polixis_mcp.shared import CachedAnswer
from polixis_mcp.shared import ResponseCache

_logger = logging.getLogger(__name__)


@runtime_checkable
class ResponseCacheStore(ResponseCache, Protocol):
    async def setup(self) -> None: ...

    async def close(self) -> None: ...

    async def cull(self, *, max_bytes: int) -> None:
        """Deletes the expired answers, then the least recently used ones until the bodies
        left come to at most `max_bytes`.
        """
        ...


class PostgresResponseCache:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine: AsyncEngine = engine

    async def setup(self) -> None:
        """Connects now, so a database the server cannot reach stops it from starting."""
        async with self._engine.connect():
            pass

    async def close(self) -> None:
        await self._engine.dispose()

    async def get(self, key: str) -> CachedAnswer | None:
        # A read is a use: it moves the answer to the back of the eviction order.
        touch = (
            update(ResponseCacheRow)
            .where(ResponseCacheRow.key == key, ResponseCacheRow.expires_at > func.now())
            .values(last_used_at=func.now(), reads=ResponseCacheRow.reads + 1)
            .returning(ResponseCacheRow.body, ResponseCacheRow.cached_at)
        )
        async with self._engine.begin() as connection:
            row = (await connection.execute(touch)).one_or_none()
        if row is None:
            return None
        body, cached_at = row
        return CachedAnswer(cached_at=cached_at, body=body)

    async def put(self, key: str, answer: CachedAnswer, *, ttl_seconds: int) -> None:
        row = insert(ResponseCacheRow).values(
            key=key,
            body=answer.body,
            cached_at=answer.cached_at,
            expires_at=answer.cached_at + timedelta(seconds=ttl_seconds),
            last_used_at=func.now(),
        )
        upsert = row.on_conflict_do_update(
            index_elements=[ResponseCacheRow.key],
            set_={
                "body": row.excluded.body,
                "cached_at": row.excluded.cached_at,
                "expires_at": row.excluded.expires_at,
                "last_used_at": row.excluded.last_used_at,
                "reads": 0,
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(upsert)

    async def cull(self, *, max_bytes: int) -> None:
        # Keeps the most recently used answers whose sizes add up to at most `max_bytes`.
        ranked = select(
            ResponseCacheRow.key,
            func.sum(ResponseCacheRow.size_bytes)
            .over(
                order_by=(ResponseCacheRow.last_used_at.desc(), ResponseCacheRow.key),
                rows=(None, 0),
            )
            .label("kept_bytes"),
        ).subquery()
        evict = delete(ResponseCacheRow).where(
            ResponseCacheRow.key.in_(select(ranked.c.key).where(ranked.c.kept_bytes > max_bytes))
        )
        async with self._engine.begin() as connection:
            await connection.execute(
                delete(ResponseCacheRow).where(ResponseCacheRow.expires_at <= func.now())
            )
            evicted = (await connection.execute(evict)).rowcount
        if evicted:
            _logger.info(
                "Deleted the least recently used Polixis answers to keep the cache under its size",
                extra={"evicted": evicted, "max_bytes": max_bytes},
            )
