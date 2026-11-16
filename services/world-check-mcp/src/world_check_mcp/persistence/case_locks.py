from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from contextlib import asynccontextmanager
from typing import Protocol, runtime_checkable

import asyncpg
from asyncpg.pool import PoolConnectionProxy

_ACQUIRE_TIMEOUT_SECONDS = 2


class CaseLease(Protocol):
    """What the holder of a case lock calls right before its write."""

    async def ensure_held(self) -> None:
        """Refuse with the holder's exception when the lock is no longer certainly held.

        The lock can still end between this call and the write, which this cannot close.
        """


@runtime_checkable
class CaseLocks(Protocol):
    """One lock per case that refuses a second holder instead of waiting for the first.

    Waiting would let a write that was approved against an earlier state run after it.
    """

    def hold(
        self, case_system_id: str, *, refuse: Exception
    ) -> AbstractAsyncContextManager[CaseLease]: ...


class _PostgresLease:
    def __init__(self, connection: PoolConnectionProxy, *, refuse: Exception) -> None:
        self._connection: PoolConnectionProxy = connection
        self._refuse: Exception = refuse

    async def ensure_held(self) -> None:
        """A round trip on the lock's own connection, which asyncpg never replaces: while it
        answers, Postgres has not ended the session and the advisory lock is still held.
        """
        try:
            await self._connection.fetchval("SELECT 1")  # pyright: ignore[reportAny]
        except asyncpg.PostgresError, asyncpg.InterfaceError, OSError:
            raise self._refuse from None


class PostgresCaseLocks:
    """A Postgres advisory lock, so every replica of the server sees the same holder. It takes one
    pooled connection while held, and Postgres frees it if that connection dies. A full pool refuses
    after a short wait rather than queueing, since a queued approval would run after the first.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool: asyncpg.Pool = pool

    @asynccontextmanager
    async def hold(self, case_system_id: str, *, refuse: Exception) -> AsyncGenerator[CaseLease]:
        key = f"world-check-mcp:case:{case_system_id}"
        # asyncpg ships no type hints, so what it returns is unknown to the type check.
        try:
            connection = await self._pool.acquire(timeout=_ACQUIRE_TIMEOUT_SECONDS)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        except TimeoutError:
            raise refuse from None
        try:
            locked: bool = await connection.fetchval(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                "SELECT pg_try_advisory_lock(hashtextextended($1, 0))", key
            )
            if not locked:
                raise refuse
            try:
                yield _PostgresLease(connection, refuse=refuse)  # pyright: ignore[reportUnknownArgumentType]
            finally:
                # A closed connection has lost the lock with its session, so there is none to free.
                if not connection.is_closed():  # pyright: ignore[reportUnknownMemberType]
                    await connection.execute(  # pyright: ignore[reportUnknownMemberType]
                        "SELECT pg_advisory_unlock(hashtextextended($1, 0))", key
                    )
        finally:
            await self._pool.release(connection)  # pyright: ignore[reportUnknownMemberType]


class _InMemoryLease:
    async def ensure_held(self) -> None:
        return None


class InMemoryCaseLocks:
    """For one process only, such as the tests."""

    def __init__(self) -> None:
        self._held: set[str] = set()

    @asynccontextmanager
    async def hold(self, case_system_id: str, *, refuse: Exception) -> AsyncGenerator[CaseLease]:
        if case_system_id in self._held:
            raise refuse
        self._held.add(case_system_id)
        try:
            yield _InMemoryLease()
        finally:
            self._held.discard(case_system_id)
