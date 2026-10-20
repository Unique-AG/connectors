import asyncio
from typing import override

import httpx2

from mcp_runtime.settings import RetrySettings


class RetryingTransport(httpx2.AsyncBaseTransport):
    """Sends a request again on a status in `retry.statuses`.

    It waits for the response's `Retry-After`, or an exponential backoff without one, as long as
    the wait stays within `retry.max_wait_seconds`.
    """

    def __init__(self, inner: httpx2.AsyncBaseTransport, retry: RetrySettings) -> None:
        self._inner: httpx2.AsyncBaseTransport = inner
        self._retry: RetrySettings = retry

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        attempt = 1
        response = await self._inner.handle_async_request(request)
        while (
            attempt < self._retry.max_attempts
            and (delay := self._delay(response, attempt)) is not None
        ):
            await response.aclose()
            await asyncio.sleep(delay)
            attempt += 1
            response = await self._inner.handle_async_request(request)
        return response

    @override
    async def aclose(self) -> None:
        await self._inner.aclose()

    def _delay(self, response: httpx2.Response, attempt: int) -> float | None:
        if response.status_code not in self._retry.statuses:
            return None
        retry_after = response.headers.get("Retry-After", "")
        if not retry_after.isdigit():
            return min(2.0 ** (attempt - 1), self._retry.max_wait_seconds)
        # A quota that resets in an hour is better reported now than waited out.
        return float(retry_after) if float(retry_after) <= self._retry.max_wait_seconds else None
