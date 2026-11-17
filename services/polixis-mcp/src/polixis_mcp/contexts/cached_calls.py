from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from datetime import UTC
import logging

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError

from polixis_mcp.persistence import cache_response
from polixis_mcp.persistence import cached_response
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import Operation
from polixis_mcp.upstream import Upstream

_logger = logging.getLogger(__name__)


async def cached_call[T: BaseModel, R: BaseModel](
    *, upstream: Upstream, persistence: Persistence, operation: Operation[T, R], request: R
) -> T:
    """The response to the same request answered within the cache's TTL, else Polixis's, which
    spares the API key's quota. Polixis returns a whole tree, graph or set of records at once and
    the tools page through it, so the next page, or another tool on the same entity, reads it
    from the cache, as does the same search or profile asked again. `freshness` reports when
    the oldest answer read from the cache was cached.

    Only a successful response is cached: `upstream.call` returns one only after its status,
    its retries and the client's rejection check have passed, and raises otherwise. A cached
    response that no longer fits the model, such as after a deploy changed it, is fetched again.
    The cache is optional: a failed read asks Polixis, and a failed write still returns its answer.
    """
    key = cache_key(operation, request)
    try:
        cached = await cached_response(persistence=persistence, key=key)
    except Exception:
        _logger.warning(
            "Could not read the Polixis response cache, asking Polixis",
            extra={"operation_id": operation.operation_id},
            exc_info=True,
        )
        cached = None
    if cached is not None:
        try:
            response = operation.adapter.validate_python(cached.response)
        except ValidationError:
            _logger.warning(
                "Fetched a cached Polixis response again: it no longer fits its model",
                extra={"operation_id": operation.operation_id},
                exc_info=True,
            )
        else:
            _reads().record(cached.cached_at)
            return response
    response = await upstream.call(operation, request)
    try:
        await cache_response(
            persistence=persistence,
            key=key,
            response=response.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
    except Exception:
        # The answer is paid for already; failing the call would only spend the quota again.
        _logger.warning(
            "Could not cache a Polixis response",
            extra={"operation_id": operation.operation_id},
            exc_info=True,
        )
    return response


def cache_key[T: BaseModel, R: BaseModel](operation: Operation[T, R], request: R) -> str:
    return f"{operation.operation_id}:{request.model_dump_json(by_alias=True, exclude_unset=True)}"


class Freshness(BaseModel):
    """Computed by this MCP: when this result was put together, and whether any of its data came
    from this server's cache of Polixis's answers rather than from Polixis on this call.
    """

    fetched_at: AwareDatetime = Field(description="When this server put this result together.")
    cached_at: AwareDatetime | None = Field(
        description=(
            "Null when all of this result came from Polixis on this call. Otherwise some or all "
            "of it came from this server's cache, and this is when Polixis's answer was cached, "
            "the oldest one when several were: the data is as of then, at most an hour before "
            "`fetched_at`. When its age matters, as for sanctions or PEP status, tell the user "
            "the data is as of this time."
        )
    )


@contextmanager
def tracking_freshness() -> Generator[None]:
    """Records the cached answers one tool call reads, for its `freshness`. The server opens it
    around every tool call.
    """
    token = _cache_reads.set(_CacheReads())
    try:
        yield
    finally:
        _cache_reads.reset(token)


def freshness() -> Freshness:
    """The freshness of the result the current tool call is putting together."""
    return Freshness(fetched_at=datetime.now(UTC), cached_at=_reads().oldest)


class _CacheReads:
    """Held in a context variable rather than set on it, so the requests a tool sends at once, each
    in a task with its own copy of the context, all record to the same one.
    """

    def __init__(self) -> None:
        self.oldest: datetime | None = None

    def record(self, cached_at: datetime) -> None:
        self.oldest = cached_at if self.oldest is None else min(self.oldest, cached_at)


_cache_reads: ContextVar[_CacheReads | None] = ContextVar("polixis_cache_reads", default=None)


def _reads() -> _CacheReads:
    reads = _cache_reads.get()
    assert reads is not None, "a tool call reads Polixis inside tracking_freshness()"
    return reads
