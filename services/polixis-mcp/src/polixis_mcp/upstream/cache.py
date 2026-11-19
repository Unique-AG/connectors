"""Polixis's answers, reused from Postgres to answer the same request again, which spares
the API key's quota. Polixis returns a whole tree, graph or set of records at once and the tools
page through it, so the next page, or another tool on the same entity, reads it from the cache,
as does the same search or profile asked again.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from datetime import timedelta
import hashlib
import json
import logging
from typing import ClassVar, override

import httpx2
from mcp_configs import shared_config
from pydantic import Field
from pydantic import JsonValue
from pydantic import model_validator
from pydantic import TypeAdapter
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from polixis_mcp.shared import CachedAnswer
from polixis_mcp.shared import ResponseCache

_logger = logging.getLogger(__name__)

CACHE_STORED_AT_HEADER = "x-internal-mcp-cache-stored-at"

# Whether a 200's body is an answer to the request worth reusing: one that fits the model of the
# operation it answers, and is not a rejection.
type AnswerCheck = Callable[[httpx2.Request, bytes], bool]


class CacheSettings(BaseSettings):
    """A changed `key_prefix` leaves every answer cached under the old one unread, until it expires
    and the cull deletes it.
    """

    model_config: ClassVar[SettingsConfigDict] = shared_config("UPSTREAM_CACHE_")

    enabled: bool = True
    ttl_seconds: int = Field(default=15 * 60, ge=1)
    key_prefix: str = Field(default="v1", pattern=r"^[A-Za-z0-9._-]{1,40}$")
    # Polixis updates its data in real time, so a TTL past an hour needs this too. It spares the
    # API key further requests while developing.
    ttl_uncapped: bool = False
    # The bodies cached, in megabytes of 1,000,000 bytes, past which each cull deletes the least
    # recently read. An answer averages about 200 KB, so 500 holds about 2,500 of them.
    max_megabytes: int = Field(default=500, ge=1)

    @model_validator(mode="after")
    def _ttl_capped_unless_uncapped(self) -> CacheSettings:
        assert self.ttl_seconds <= _CAPPED_TTL_SECONDS or self.ttl_uncapped, (
            f"UPSTREAM_CACHE_TTL_SECONDS is at most {_CAPPED_TTL_SECONDS} "
            "unless UPSTREAM_CACHE_TTL_UNCAPPED=true"
        )
        return self


class CachingTransport(httpx2.AsyncBaseTransport):
    """Answers a request from `cache` when the same one was answered within the TTL, else sends
    it and caches the answer. A cached answer carries `CACHE_STORED_AT_HEADER`, when it was
    cached, which `record_cache_read` reads for the tool's `freshness`.

    The body is kept as Polixis sent it, and only one `usable` accepts is cached or reused: a 200
    whose body does not fit the operation's model is not cached, and neither is a rejection,
    which Polixis sends with a 200 for an id it does not know. A cached answer that no longer
    fits, as after a deploy that changed the model, is fetched again, and the fresh answer, if
    it fits, replaces it. The cache is optional: a failed read sends the request, and a failed
    write still returns Polixis's answer.

    The key binds an answer to the upstream's origin, so a deployment pointed at another Polixis
    reads none of the first one's answers. It does not bind it to the credentials: every account
    gets the same data.

    Requests in one replica that miss under the same key at once send one request: the others
    wait for it, at most `wait_seconds`, and read its answer from the cache if it kept one.
    """

    def __init__(
        self,
        inner: httpx2.AsyncBaseTransport,
        *,
        cache: ResponseCache,
        settings: CacheSettings,
        usable: AnswerCheck,
        wait_seconds: float,
        now: Callable[[], datetime],
    ) -> None:
        self._inner: httpx2.AsyncBaseTransport = inner
        self._cache: ResponseCache = cache
        self._settings: CacheSettings = settings
        self._usable: AnswerCheck = usable
        self._wait_seconds: float = wait_seconds
        self._now: Callable[[], datetime] = now
        self._fetches: dict[str, _Fetch] = {}

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        key = f"{self._settings.key_prefix}:{await _request_key(request)}"
        async with self._joined(key) as fetch:
            # Read before the lookup, so an answer cached while it ran is read again below.
            published = fetch.published
            cached = await self._read(key, request)
            if cached is None:
                async with self._turn(fetch) as turn:
                    if turn and fetch.published != published:
                        cached = await self._read(key, request)
                    if cached is None:
                        return await self._fetch(key, request, fetch)
        return httpx2.Response(
            _OK,
            content=cached.body,
            headers={
                "content-type": "application/json",
                CACHE_STORED_AT_HEADER: cached.cached_at.isoformat(),
            },
            request=request,
        )

    @override
    async def aclose(self) -> None:
        await self._inner.aclose()

    @asynccontextmanager
    async def _joined(self, key: str) -> AsyncGenerator[_Fetch]:
        """`key`'s fetch, which is dropped once no request for the key is in flight."""
        fetch = self._fetches.setdefault(key, _Fetch())
        fetch.requests += 1
        try:
            yield fetch
        finally:
            fetch.requests -= 1
            if fetch.requests == 0:
                del self._fetches[key]

    @asynccontextmanager
    async def _turn(self, fetch: _Fetch) -> AsyncGenerator[bool]:
        """Holds the fetch's lock, or after `wait_seconds` without it goes on regardless. Yields
        whether it holds it.
        """
        try:
            async with asyncio.timeout(self._wait_seconds):
                _ = await fetch.lock.acquire()
        except TimeoutError:
            turn = False
        else:
            turn = True
        try:
            yield turn
        finally:
            if turn:
                fetch.lock.release()

    async def _fetch(self, key: str, request: httpx2.Request, fetch: _Fetch) -> httpx2.Response:
        response = await self._inner.handle_async_request(request)
        if response.status_code == _OK:
            await response.aread()
            if await self._write(key, request, response):
                fetch.published += 1
        return response

    async def _read(self, key: str, request: httpx2.Request) -> CachedAnswer | None:
        """None for an answer cached longer ago than the TTL now set, as after a restart with a
        shorter one, or that no longer fits its model, which is then fetched again.
        """
        try:
            cached = await self._cache.get(key)
        except Exception:
            _logger.warning(
                "Could not read the Polixis response cache, asking Polixis",
                extra={"path": request.url.path},
                exc_info=True,
            )
            return None
        if cached is None:
            return None
        if self._now() - cached.cached_at > timedelta(seconds=self._settings.ttl_seconds):
            return None
        if not self._usable(request, cached.body):
            _logger.warning(
                "Fetching a cached Polixis answer again: it no longer fits its model",
                extra={"path": request.url.path},
            )
            return None
        return cached

    async def _write(self, key: str, request: httpx2.Request, response: httpx2.Response) -> bool:
        """Whether the answer was cached."""
        if not self._usable(request, response.content):
            return False
        answer = CachedAnswer(cached_at=self._now(), body=response.content)
        try:
            await self._cache.put(key, answer, ttl_seconds=self._settings.ttl_seconds)
        except Exception:
            # The answer is paid for already; failing the call would only spend the quota again.
            _logger.warning(
                "Could not cache a Polixis response",
                extra={"path": request.url.path},
                exc_info=True,
            )
            return False
        return True


@contextmanager
def tracking_cache_reads() -> Generator[None]:
    """Records the cached answers one tool call reads, for its `freshness`. The server opens it
    around every tool call.
    """
    token = _cache_reads.set(_CacheReads())
    try:
        yield
    finally:
        _cache_reads.reset(token)


def oldest_cache_read() -> datetime | None:
    """When the oldest cached answer the current tool call read was cached, None when it read
    none.
    """
    reads = _cache_reads.get()
    assert reads is not None, "a tool call reads Polixis inside tracking_cache_reads()"
    return reads.oldest


async def record_cache_read(response: httpx2.Response) -> None:
    """An httpx response hook. Outside a tool call nothing records it. A tool served from the
    spec records it too, but reports no freshness.
    """
    stored_at = response.headers.get(CACHE_STORED_AT_HEADER)
    reads = _cache_reads.get()
    if stored_at is not None and reads is not None:
        reads.record(datetime.fromisoformat(stored_at))


class _Fetch:
    """The requests in flight for one key: how many there are, the lock the one that sends it
    holds, and how many answers they have cached.
    """

    def __init__(self) -> None:
        self.lock: asyncio.Lock = asyncio.Lock()
        self.requests: int = 0
        self.published: int = 0


class _CacheReads:
    """Held in a context variable rather than set on it, so the requests a tool sends at once, each
    in a task with its own copy of the context, all record to the same one.
    """

    def __init__(self) -> None:
        self.oldest: datetime | None = None

    def record(self, cached_at: datetime) -> None:
        self.oldest = cached_at if self.oldest is None else min(self.oldest, cached_at)


async def _request_key(request: httpx2.Request) -> str:
    """The method, origin and path, readable, and a digest of the query and the body: the
    headers, the token among them, and any credentials in the URL play no part.
    """
    content = await request.aread()
    try:
        body: JsonValue = _JSON.validate_json(content) if content else None
    except ValueError:
        body = content.decode(errors="replace")
    query = sorted(request.url.params.multi_items())
    canonical = json.dumps([query, body], sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    origin = f"{request.url.scheme}://{request.url.netloc.decode('ascii')}"
    return f"{request.method} {origin}{encoded_path(request.url)}:{digest}"


def encoded_path(url: httpx2.URL) -> str:
    """The path as sent, so `/a%2Fb` and `/a/b`, which an upstream may route apart, stay apart."""
    return url.raw_path.partition(b"?")[0].decode("ascii")


_cache_reads: ContextVar[_CacheReads | None] = ContextVar("polixis_cache_reads", default=None)
_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_CAPPED_TTL_SECONDS = 60 * 60
_OK = 200
