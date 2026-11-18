import asyncio
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
import logging
from typing import override

import httpx2
from mcp_openapi.upstream import UpstreamError

_logger = logging.getLogger(__name__)

_TOO_MANY_REQUESTS = 429


class QuotaGate:
    """Polixis answers every request with a 429 once the API key's quota is spent, and says
    neither when it resets nor how much is left. Its first such answer fails the call with
    `PolixisQuotaSpentError`, and after it this gate refuses every request of the process for
    `cooldown` without sending it, then lets the next one through to learn whether the quota has
    been raised. Each process learns it on its own, so a spent quota costs one request per
    process per cooldown.

    It raises from the client's transport and response hook, so neither the retry policy,
    which only retries an `HTTPStatusError`, nor the tools served from the spec ever see the
    429 itself.
    """

    def __init__(self, *, cooldown: timedelta, now: Callable[[], datetime]) -> None:
        self._cooldown: timedelta = cooldown
        self._now: Callable[[], datetime] = now
        self._spent_until: datetime | None = None

    def refuse_while_spent(self) -> None:
        if self._spent_until is not None and self._now() < self._spent_until:
            raise PolixisQuotaSpentError()

    async def record(self, response: httpx2.Response) -> None:
        """An httpx response hook."""
        if is_quota_spent(response):
            self._spent_until = self._now() + self._cooldown
            _logger.warning(
                "Polixis answered that the API key's request quota is spent",
                extra={"refused_until": self._spent_until.isoformat()},
            )
            raise PolixisQuotaSpentError()


class AdmissionTransport(httpx2.AsyncBaseTransport):
    """Sends at most `slots` requests at once and asks the quota gate only once a request has
    its slot, so the ones that waited for a slot are refused, not sent, after Polixis says the
    quota is spent. The slot frees when the response headers arrive, after the client's
    response hooks have recorded a spent quota and before any other request runs.
    """

    def __init__(self, inner: httpx2.AsyncBaseTransport, *, slots: int, quota: QuotaGate) -> None:
        self._inner: httpx2.AsyncBaseTransport = inner
        self._slots: asyncio.Semaphore = asyncio.Semaphore(slots)
        self._quota: QuotaGate = quota

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        async with self._slots:
            self._quota.refuse_while_spent()
            return await self._inner.handle_async_request(request)

    @override
    async def aclose(self) -> None:
        await self._inner.aclose()


def is_quota_spent(response: httpx2.Response) -> bool:
    """AWS API Gateway marks a spent usage-plan quota, unlike a throttled request, which is a
    `TooManyRequestsException` worth retrying.
    """
    return response.status_code == _TOO_MANY_REQUESTS and response.headers.get(
        "x-amzn-errortype", ""
    ).startswith("LimitExceededException")


class PolixisQuotaSpentError(UpstreamError):
    """Polixis refuses every request: the API key's request quota is spent. Its message is for
    the agent, which would otherwise retry a call that cannot succeed until an administrator
    buys more requests.
    """

    def __init__(self) -> None:
        super().__init__(
            "The Polixis API request limit was exceeded. This server does not retry the request, "
            "since Polixis answers no more requests until more are added to the limit. Do not "
            "call this tool or any other Polixis tool again in this conversation. Tell the user "
            "that the Polixis API request limit was exceeded and that they should ask their "
            "administrator to get more Polixis API requests.",
            status_code=_TOO_MANY_REQUESTS,
        )
