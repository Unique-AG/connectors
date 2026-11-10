from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from typing import ClassVar

import httpx2
from mcp_openapi.retry import RetryAfterPolicy
from mcp_openapi.upstream import UpstreamError
from pydantic import BaseModel
from pydantic import ConfigDict
import tenacity

_TOO_MANY_REQUESTS = 429


class QuotaGate:
    """Polixis answers every request with a 429 once the API key's quota is spent, and says
    neither when it resets nor how much is left. After the first such answer this gate refuses
    every request of the process for `cooldown` without sending it, then lets the next one
    through to learn whether the quota has reset. Each process learns it on its own, so a spent
    quota costs one request per process per cooldown.
    """

    def __init__(self, *, cooldown: timedelta, now: Callable[[], datetime]) -> None:
        self._cooldown: timedelta = cooldown
        self._now: Callable[[], datetime] = now
        self._spent_until: datetime | None = None

    async def refuse_while_spent(self, request: httpx2.Request) -> None:
        """An httpx request hook."""
        if self._spent_until is not None and self._now() < self._spent_until:
            raise PolixisQuotaSpentError(
                f"Polixis's request quota for this API key is spent. {request.method} "
                f"{request.url.copy_with(query=None)} was not sent: this server does not ask "
                f"Polixis again before {self._spent_until:%H:%M} UTC, and the quota itself may "
                "reset later than that."
            )

    async def record(self, response: httpx2.Response) -> None:
        """An httpx response hook."""
        if is_quota_spent(response):
            self._spent_until = self._now() + self._cooldown


class QuotaAwareRetryPolicy(BaseModel):
    """`retry_after`'s retries, except for a spent quota: sending the request again cannot
    succeed before the quota resets, and only spends more of the next one.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    retry_after: RetryAfterPolicy

    def retrying(self) -> tenacity.AsyncRetrying:
        retrying = self.retry_after.retrying()
        return retrying.copy(
            retry=tenacity.retry_all(
                tenacity.retry_if_exception(lambda error: not _is_quota_error(error)),
                retrying.retry,
            )
        )


def is_quota_spent(response: httpx2.Response) -> bool:
    """AWS API Gateway marks a spent usage-plan quota, unlike a throttled request, which is a
    `TooManyRequestsException` worth retrying.
    """
    return response.status_code == _TOO_MANY_REQUESTS and response.headers.get(
        "x-amzn-errortype", ""
    ).startswith("LimitExceededException")


def _is_quota_error(error: BaseException) -> bool:
    return isinstance(error, httpx2.HTTPStatusError) and is_quota_spent(error.response)


class PolixisQuotaSpentError(UpstreamError):
    """A request not sent, because Polixis answered recently that the quota is spent."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=_TOO_MANY_REQUESTS)
