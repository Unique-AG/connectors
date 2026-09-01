"""When to try an upstream request again.

429 is documented on every path with no published budget, so it is retried with backoff and a
`Retry-After` honoured when sent. 5xx and network errors are retried; 4xx other than 429 are
not — a 403 will be a 403 next time too.
"""

from dataclasses import dataclass

from with_intelligence_mcp.with_intelligence_client.errors import RateLimited, Unreachable
from with_intelligence_mcp.with_intelligence_client.settings import RetrySettings


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    max_wait_seconds: float

    @classmethod
    def from_settings(cls, settings: RetrySettings) -> "RetryPolicy":
        return cls(
            max_attempts=settings.max_attempts,
            max_wait_seconds=settings.max_wait_ms / 1000,
        )

    def should_retry(self, error: BaseException, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        return isinstance(error, (RateLimited, Unreachable))

    def wait_seconds(self, error: BaseException, attempt: int) -> float:
        """Exponential backoff, capped — or the server's own `Retry-After` when it sent one."""
        if isinstance(error, RateLimited) and error.retry_after_seconds is not None:
            return min(error.retry_after_seconds, self.max_wait_seconds)
        return min(2.0 ** (attempt - 1), self.max_wait_seconds)
