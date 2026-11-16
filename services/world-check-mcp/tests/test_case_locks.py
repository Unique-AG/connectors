from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import asyncpg
import pytest

from world_check_mcp.persistence.case_locks import PostgresCaseLocks


class _Connection:
    def __init__(self, *, free: bool) -> None:
        self.free: bool = free
        self.statements: list[str] = []

    async def fetchval(self, query: str, *_args: object) -> bool:
        self.statements.append(query)
        return self.free

    async def execute(self, query: str, *_args: object) -> None:
        self.statements.append(query)


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self._connection: _Connection = connection

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[_Connection]:
        yield self._connection


def _locks(connection: _Connection) -> PostgresCaseLocks:
    return PostgresCaseLocks(cast(asyncpg.Pool, cast(object, _Pool(connection))))


async def test_a_free_case_is_locked_and_unlocked_on_the_same_connection() -> None:
    connection = _Connection(free=True)

    async with _locks(connection).hold("sys-1", refuse=ValueError("busy")):
        assert len(connection.statements) == 1

    assert "pg_try_advisory_lock" in connection.statements[0]
    assert "pg_advisory_unlock" in connection.statements[1]


async def test_a_case_held_by_another_replica_is_refused_without_unlocking() -> None:
    connection = _Connection(free=False)

    with pytest.raises(ValueError, match="busy"):
        async with _locks(connection).hold("sys-1", refuse=ValueError("busy")):
            pytest.fail("the body must not run")

    assert len(connection.statements) == 1


async def test_the_lock_is_released_when_the_write_fails() -> None:
    connection = _Connection(free=True)

    with pytest.raises(RuntimeError, match="write failed"):
        async with _locks(connection).hold("sys-1", refuse=ValueError("busy")):
            raise RuntimeError("write failed")

    assert "pg_advisory_unlock" in connection.statements[-1]
