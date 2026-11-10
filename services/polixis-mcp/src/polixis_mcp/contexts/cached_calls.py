import logging

from pydantic import BaseModel
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
    """The response to the same request answered in the last few minutes, else Polixis's. Polixis
    returns a whole tree, graph or set of records at once and the tools page through it, so the
    next page, or another tool on the same entity, reads it from the cache.

    Only a successful response is cached: `upstream.call` returns one only after its status,
    its retries and the client's rejection check have passed, and raises otherwise. A cached
    response that no longer fits the model, such as after a deploy changed it, is fetched again.
    """
    key = cache_key(operation, request)
    cached = await cached_response(persistence=persistence, key=key)
    if cached is not None:
        try:
            return operation.adapter.validate_python(cached)
        except ValidationError:
            _logger.warning(
                "Fetched a cached Polixis response again: it no longer fits its model",
                extra={"operation_id": operation.operation_id},
                exc_info=True,
            )
    response = await upstream.call(operation, request)
    await cache_response(
        persistence=persistence,
        key=key,
        response=response.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
    return response


def cache_key[T: BaseModel, R: BaseModel](operation: Operation[T, R], request: R) -> str:
    return f"{operation.operation_id}:{request.model_dump_json(by_alias=True, exclude_unset=True)}"
