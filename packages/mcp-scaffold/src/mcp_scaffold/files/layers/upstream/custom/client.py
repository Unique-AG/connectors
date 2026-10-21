from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
import logging

from fastmcp.exceptions import ToolError
import httpx2
from mcp_openapi.retry import RetryAfterPolicy
from mcp_openapi.retry import RetryPolicy
from pydantic import TypeAdapter
from pydantic import ValidationError

from mcp_skeleton.upstream.settings import UpstreamSettings

_LOGGER = logging.getLogger(__name__)
_LOGGED_BODY_CHARS = 200


class UpstreamError(ToolError):
    """The upstream failed, or its body does not fit the model. It reaches the MCP client."""


class Upstream:
    """The upstream's client: one `request` for any method and path, parsed into a model.

    Each request is retried by `retry_policy`. For a status or header of the upstream's own, such
    as a 502 or `X-RateLimit-Reset`, pass another `mcp_openapi.retry.RetryPolicy`.
    """

    def __init__(self, http: httpx2.AsyncClient, retry_policy: RetryPolicy) -> None:
        self._http: httpx2.AsyncClient = http
        self._retry_policy: RetryPolicy = retry_policy

    async def request[T](
        self,
        method: str,
        path: str,
        adapter: TypeAdapter[T],
        *,
        params: Mapping[str, str | int | float | bool] | None = None,
        json: object = None,
    ) -> T:
        """Sends `method` to `path` and parses the JSON body with `adapter`.

        `path` is relative to the base URL, which keeps the auth on it. Anything else is a
        ValueError. An error status, a transport error or a body that does not fit `adapter` is
        an UpstreamError.
        """
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError(f"{path} is not a path")
        request = self._http.build_request(method, path, params=params, json=json)
        content = await self._send(request)
        try:
            return adapter.validate_json(content)
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(map(str, problem['loc'])) or 'body'}: {problem['msg']}"
                for problem in error.errors()
            )
            raise UpstreamError(f"Unexpected response: {problems}") from error

    async def _send(self, request: httpx2.Request) -> bytes:
        try:
            return await self._retry_policy.retrying()(self._attempt, request)
        except httpx2.HTTPStatusError as error:
            url = error.request.url.copy_with(query=None)
            status = f"{error.response.status_code} {error.response.reason_phrase}"
            message = f"{status} for {error.request.method} {url}"
            # The body may hold the upstream's internals, so only the server log sees it.
            _LOGGER.warning("%s: %s", message, error.response.text[:_LOGGED_BODY_CHARS])
            raise UpstreamError(message) from error
        except httpx2.HTTPError as error:
            raise UpstreamError(str(error) or type(error).__name__) from error

    async def _attempt(self, request: httpx2.Request) -> bytes:
        response = await self._http.send(request)
        response.raise_for_status()
        return response.content


@asynccontextmanager
async def open_upstream(
    settings: UpstreamSettings, transport: httpx2.AsyncBaseTransport | None = None
) -> AsyncGenerator[Upstream]:
    retry = settings.retry
    policy = RetryAfterPolicy(
        max_attempts=retry.max_attempts,
        max_wait_seconds=retry.max_wait_seconds,
        statuses=retry.statuses,
    )
    async with httpx2.AsyncClient(
        base_url=str(settings.api_url).rstrip("/"),
        timeout=settings.timeout_seconds,
        transport=transport,
        headers={
            "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
            "Accept": "application/json",
        },
    ) as http:
        yield Upstream(http, policy)
