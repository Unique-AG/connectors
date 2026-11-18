# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

"""The server with fakes in place of the upstream and the stores. The tests build it, and so
does `uv run poe architecture`, which lists its tools.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
import httpx2
from key_value.aio.stores.memory import MemoryStore
from mcp_configs import RetrySettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr

from polixis_mcp.mcp import create_server
from polixis_mcp.persistence import Persistence
from polixis_mcp.shared import CachedAnswer
from polixis_mcp.upstream import CacheSettings
from polixis_mcp.upstream import UpstreamSettings


def fake_upstream_settings() -> UpstreamSettings:
    """Every field given, so neither the environment nor `.env` changes what the tests see.
    Retries never wait.
    """
    return UpstreamSettings(
        client_id=SecretStr("dummy-client-id"),
        client_secret=SecretStr("dummy-client-secret"),
        api_key=SecretStr("dummy-api-key"),
        api_url=AnyHttpUrl("https://api.example.com"),
        token_url=AnyHttpUrl("https://auth.example.com/token"),
        timeout_seconds=30,
        retry=RetrySettings(max_attempts=3, max_wait_seconds=0, statuses=frozenset({429, 503})),
        cache=fake_cache_settings(),
    )


def fake_cache_settings(**changes: object) -> CacheSettings:
    """Every field given, so neither the environment nor `.env` changes what the tests see."""
    settings = CacheSettings(
        enabled=True, ttl_seconds=15 * 60, key_prefix="v1", ttl_uncapped=False, max_megabytes=500
    )
    return settings.model_copy(update=changes)


def unanswered_upstream() -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda _request: httpx2.Response(404))


class FakeStore(MemoryStore):
    """`MemoryStore` drops an entry past its TTL when it is read, so a cull only counts, and it
    holds no connection to close.
    """

    culls: int = 0

    async def cull(self) -> None:
        self.culls += 1

    async def close(self) -> None:
        pass


class FakeResponseCache:
    """An in-memory `ResponseCacheStore`, which keeps every answer with its TTL and records the
    size each cull was given. The transport, not the store, ages an answer out by its TTL.
    """

    def __init__(self) -> None:
        self.answers: dict[str, CachedAnswer] = {}
        self.ttls: dict[str, int] = {}
        self.culls: list[int] = []

    async def setup(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def get(self, key: str) -> CachedAnswer | None:
        return self.answers.get(key)

    async def put(self, key: str, answer: CachedAnswer, *, ttl_seconds: int) -> None:
        self.answers[key] = answer
        self.ttls[key] = ttl_seconds

    async def cull(self, *, max_bytes: int) -> None:
        self.culls.append(max_bytes)


def fake_persistence(response_cache: FakeResponseCache | None = None) -> Persistence:
    """In-memory stores in place of Postgres."""
    return Persistence(store=FakeStore(), response_cache=response_cache or FakeResponseCache())


@asynccontextmanager
async def offline_server() -> AsyncGenerator[FastMCP]:
    yield create_server(fake_upstream_settings(), fake_persistence(), unanswered_upstream())
