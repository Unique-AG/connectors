from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from contextlib import asynccontextmanager
from typing import Protocol, runtime_checkable

import asyncpg


@runtime_checkable
class CaseLocks(Protocol):
    """One lock per case that refuses a second holder instead of waiting for the first.

    Waiting would let a write that was approved against an earlier state run after it.
    """

    def hold(
        self, case_system_id: str, *, refuse: Exception
    ) -> AbstractAsyncContextManager[None]: ...


class PostgresCaseLocks:
    """A Postgres advisory lock, so every replica of the server sees the same holder. It takes one
    pooled connection while held, and Postgres frees it if that connection dies.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool: asyncpg.Pool = pool

    @asynccontextmanager
    async def hold(self, case_system_id: str, *, refuse: Exception) -> AsyncGenerator[None]:
        key = f"world-check-mcp:case:{case_system_id}"
        # asyncpg ships no type hints, so what it returns is unknown to the type check.
        async with self._pool.acquire() as connection:  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            locked: bool = await connection.fetchval(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                "SELECT pg_try_advisory_lock(hashtextextended($1, 0))", key
            )
            if not locked:
                raise refuse
            try:
                yield
            finally:
                await connection.execute(  # pyright: ignore[reportUnknownMemberType]
                    "SELECT pg_advisory_unlock(hashtextextended($1, 0))", key
                )


class InMemoryCaseLocks:
    """For one process only, such as the tests."""

    def __init__(self) -> None:
        self._held: set[str] = set()

    @asynccontextmanager
    async def hold(self, case_system_id: str, *, refuse: Exception) -> AsyncGenerator[None]:
        if case_system_id in self._held:
            raise refuse
        self._held.add(case_system_id)
        try:
            yield
        finally:
            self._held.discard(case_system_id)
