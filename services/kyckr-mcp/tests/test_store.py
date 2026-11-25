import ssl

import asyncpg
from key_value.aio.stores.postgresql import PostgreSQLStore
from mcp_configs import PostgresSettings
from pydantic import SecretStr
import pytest

from kyckr_mcp.persistence import open_persistence
from kyckr_mcp.persistence import sign_in_store

URL = "postgresql://user:secret@db.example.com:5432/kyckr"
PoolRequest = tuple[tuple[object, ...], dict[str, object]]


def _settings(*, ssl_mode: str | None = None, pool_size: int = 5) -> PostgresSettings:
    return PostgresSettings(
        url=SecretStr(URL),
        ssl_mode=ssl_mode,
        pool_size=pool_size,
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


class FakePool:
    """Answers the store's setup as if its table existed, and records that it was closed."""

    closed: bool = False

    async def fetchval(self, *_: object) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def pool_requests(monkeypatch: pytest.MonkeyPatch) -> list[PoolRequest]:
    """What the store asked asyncpg for, answered without a database."""
    requests: list[PoolRequest] = []

    async def create_pool(*args: object, **kwargs: object) -> FakePool:
        requests.append((args, kwargs))
        return FakePool()

    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    return requests


async def _set_up(settings: PostgresSettings) -> PostgreSQLStore:
    store = sign_in_store(settings)
    await store.setup()
    return store


async def test_the_sign_in_store_opens_one_small_pool_and_persistence_closes_it(
    pool_requests: list[PoolRequest],
) -> None:
    store = await _set_up(_settings(pool_size=3))

    async with open_persistence(store):
        pass

    ((dsn,), options), *others = pool_requests
    assert others == []
    assert dsn == URL
    assert options == {"min_size": 1, "max_size": 3, "statement_cache_size": 100}
    assert isinstance(store._pool, FakePool)
    assert store._pool.closed


async def test_the_pool_verifies_the_server_as_the_chart_asks(
    pool_requests: list[PoolRequest],
) -> None:
    await _set_up(_settings(ssl_mode="verify-full"))

    _, options = pool_requests[0]
    tls = options["ssl"]
    assert isinstance(tls, ssl.SSLContext)
    assert tls.verify_mode is ssl.CERT_REQUIRED


@pytest.mark.parametrize("ssl_mode", ["disable", "allow", "prefer"])
async def test_the_pool_passes_the_modes_that_may_fall_back_to_plain_text_by_name(
    pool_requests: list[PoolRequest], ssl_mode: str
) -> None:
    await _set_up(_settings(ssl_mode=ssl_mode))

    _, options = pool_requests[0]
    assert options["ssl"] == ssl_mode


async def test_the_sqlalchemy_cache_option_becomes_asyncpgs_pool_argument(
    pool_requests: list[PoolRequest],
) -> None:
    settings = PostgresSettings(
        url=SecretStr(f"{URL}?prepared_statement_cache_size=0"),
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    await _set_up(settings)

    (dsn,), options = pool_requests[0]
    assert dsn == URL
    assert options["statement_cache_size"] == 0
