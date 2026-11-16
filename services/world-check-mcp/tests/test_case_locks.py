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
    def __init__(self, connection: _Connection, *, full: bool = False) -> None:
        self._connection: _Connection = connection
        self._full: bool = full
        self.released: int = 0

    async def acquire(self, *, timeout: float) -> _Connection:
        if self._full:
            raise TimeoutError
        assert timeout > 0
        return self._connection

    async def release(self, _connection: _Connection) -> None:
        self.released += 1


def _locks(connection: _Connection, *, pool: _Pool | None = None) -> PostgresCaseLocks:
    return PostgresCaseLocks(cast(asyncpg.Pool, cast(object, pool or _Pool(connection))))


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


async def test_a_full_pool_refuses_instead_of_queueing() -> None:
    connection = _Connection(free=True)
    pool = _Pool(connection, full=True)

    with pytest.raises(ValueError, match="busy"):
        async with _locks(connection, pool=pool).hold("sys-1", refuse=ValueError("busy")):
            pytest.fail("the body must not run")

    assert connection.statements == []


async def test_the_connection_goes_back_to_the_pool() -> None:
    connection = _Connection(free=False)
    pool = _Pool(connection)

    with pytest.raises(ValueError, match="busy"):
        async with _locks(connection, pool=pool).hold("sys-1", refuse=ValueError("busy")):
            pytest.fail("the body must not run")

    assert pool.released == 1
