from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from datetime import UTC
from email.utils import parsedate_to_datetime

from fastmcp.exceptions import ToolError
import httpx2
from mcp_configs import RetrySettings
from pydantic import TypeAdapter
from pydantic import ValidationError
import tenacity

from mcp_skeleton.upstream.settings import UpstreamSettings

# A 503 may come from a gateway after the upstream applied the request, so only a request that is
# safe to apply twice is sent again on it. A 429 means the upstream turned the request away.
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE", "TRACE"})
_TOO_MANY_REQUESTS = 429
_BACKOFF = tenacity.wait_exponential_jitter(initial=1, exp_base=2, jitter=1)


class UpstreamError(ToolError):
    """The upstream failed, or its body does not fit the model. It reaches the MCP client."""


class Upstream:
    """The upstream's client: one `request` for any method and path, parsed into a model.

    Retries follow mcp-openapi's `RetryAfterPolicy` with `RetrySettings`: a status in `statuses`
    is sent again after its `Retry-After`, or an exponential backoff with jitter without one, as
    long as the wait stays within `max_wait_seconds`. Any request is sent again on a 429, and only
    an idempotent one on another status.
    """

    def __init__(self, http: httpx2.AsyncClient, retry: RetrySettings) -> None:
        self._http: httpx2.AsyncClient = http
        self._retry: RetrySettings = retry

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
        # Tenacity keeps a call's state in a thread-local that every coroutine on the loop shares,
        # so each request gets its own AsyncRetrying.
        retrying = tenacity.AsyncRetrying(
            retry=self._should_retry,
            wait=self._wait,
            stop=tenacity.stop_after_attempt(self._retry.max_attempts),
            reraise=True,
        )
        try:
            return await retrying(self._attempt, request)
        except httpx2.HTTPStatusError as error:
            url = error.request.url.copy_with(query=None)
            status = f"{error.response.status_code} {error.response.reason_phrase}"
            message = f"{status} for {error.request.method} {url}"
            body = error.response.text[:200]
            raise UpstreamError(f"{message}: {body}" if body else message) from error
        except httpx2.HTTPError as error:
            raise UpstreamError(str(error) or type(error).__name__) from error

    async def _attempt(self, request: httpx2.Request) -> bytes:
        response = await self._http.send(request)
        response.raise_for_status()
        return response.content

    def _should_retry(self, state: tenacity.RetryCallState) -> bool:
        response = _failed_response(state)
        if response is None or response.status_code not in self._retry.statuses:
            return False
        if (
            response.status_code != _TOO_MANY_REQUESTS
            and response.request.method not in _IDEMPOTENT_METHODS
        ):
            return False
        # A quota that resets in an hour is better reported now than waited out.
        delay = _retry_after_seconds(response)
        return delay is None or delay <= self._retry.max_wait_seconds

    def _wait(self, state: tenacity.RetryCallState) -> float:
        response = _failed_response(state)
        delay = _retry_after_seconds(response) if response is not None else None
        return min(_BACKOFF(state), self._retry.max_wait_seconds) if delay is None else delay


@asynccontextmanager
async def open_upstream(
    settings: UpstreamSettings, transport: httpx2.AsyncBaseTransport | None = None
) -> AsyncGenerator[Upstream]:
    async with httpx2.AsyncClient(
        base_url=str(settings.api_url).rstrip("/"),
        timeout=settings.timeout_seconds,
        transport=transport,
        headers={
            "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
            "Accept": "application/json",
        },
    ) as http:
        yield Upstream(http, settings.retry)


def _failed_response(state: tenacity.RetryCallState) -> httpx2.Response | None:
    outcome = state.outcome
    error = outcome.exception() if outcome is not None and outcome.failed else None
    return error.response if isinstance(error, httpx2.HTTPStatusError) else None


def _retry_after_seconds(response: httpx2.Response) -> float | None:
    """`Retry-After` as delta-seconds or an HTTP-date (RFC 9110 §10.2.3), None if unreadable."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(UTC)).total_seconds(), 0.0)
