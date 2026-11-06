import ssl

import asyncpg
from mcp_configs import PostgresSettings
from pydantic import SecretStr
import pytest

from world_check_mcp.persistence.store import _PostgresStore

URL = "postgresql://user:secret@db.example.com:5432/world_check"
PoolRequest = tuple[tuple[object, ...], dict[str, object]]


def _settings(*, ssl_mode: str | None = None, pool_size: int = 5) -> PostgresSettings:
    return PostgresSettings(
        url=SecretStr(URL),
        ssl_mode=ssl_mode,
        pool_size=pool_size,
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


@pytest.fixture
def pool_requests(monkeypatch: pytest.MonkeyPatch) -> list[PoolRequest]:
    """What the store asked asyncpg for, answered without a database."""
    requests: list[PoolRequest] = []

    async def create_pool(*args: object, **kwargs: object) -> object:
        requests.append((args, kwargs))
        return object()

    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    return requests


async def test_the_pool_connects_with_a_plain_postgres_dsn(
    pool_requests: list[PoolRequest],
) -> None:
    await _PostgresStore(_settings())._create_pool()

    (dsn,), _ = pool_requests[0]
    assert dsn == URL


async def test_the_pool_is_sized_by_the_settings_and_starts_with_one_connection(
    pool_requests: list[PoolRequest],
) -> None:
    await _PostgresStore(_settings(pool_size=3))._create_pool()

    _, options = pool_requests[0]
    assert (options["min_size"], options["max_size"]) == (1, 3)


async def test_the_pool_verifies_the_server_as_the_chart_asks(
    pool_requests: list[PoolRequest],
) -> None:
    await _PostgresStore(_settings(ssl_mode="verify-full"))._create_pool()

    _, options = pool_requests[0]
    tls = options["ssl"]
    assert isinstance(tls, ssl.SSLContext)
    assert tls.verify_mode is ssl.CERT_REQUIRED


async def test_the_pool_leaves_tls_to_asyncpg_when_the_chart_sets_none(
    pool_requests: list[PoolRequest],
) -> None:
    await _PostgresStore(_settings())._create_pool()

    _, options = pool_requests[0]
    assert "ssl" not in options


@pytest.mark.parametrize("ssl_mode", ["disable", "allow", "prefer"])
async def test_the_pool_passes_the_modes_that_may_fall_back_to_plain_text_by_name(
    pool_requests: list[PoolRequest], ssl_mode: str
) -> None:
    await _PostgresStore(_settings(ssl_mode=ssl_mode))._create_pool()

    _, options = pool_requests[0]
    assert options["ssl"] == ssl_mode
