import time
from typing import Literal

import pytest
import tenacity

from backstop_mcp.backstop_client.errors import BackstopRateLimitError
from backstop_mcp.backstop_client.retry import build_retrying
from backstop_mcp.config import BackstopConfig


def _retry_state(
    retrying: tenacity.AsyncRetrying, exc: BaseException, attempt_number: int = 1
) -> tenacity.RetryCallState:
    state = tenacity.RetryCallState(retry_object=retrying, fn=None, args=(), kwargs={})
    state.attempt_number = attempt_number
    state.set_exception((type(exc), exc, exc.__traceback__))
    return state


class TestRetryPredicate:
    def test_concurrency_breach_within_ceiling_is_retryable(self) -> None:
        config = BackstopConfig(max_retry_wait_ms=30_000)
        retrying = build_retrying(config)
        exc = BackstopRateLimitError(
            429, "Concurrency limit exceeded", limit_kind="concurrency", retry_after_seconds=1.0
        )

        assert retrying.retry(_retry_state(retrying, exc)) is True

    @pytest.mark.parametrize("limit_kind", ["minute", "hour", "day"])
    def test_quota_breach_is_never_retryable_regardless_of_ceiling(
        self, limit_kind: Literal["minute", "hour", "day"]
    ) -> None:
        config = BackstopConfig(max_retry_wait_ms=30_000)
        retrying = build_retrying(config)
        exc = BackstopRateLimitError(
            429,
            "Quota exceeded",
            limit_kind=limit_kind,
            retry_after_seconds=0.001,
        )

        assert retrying.retry(_retry_state(retrying, exc)) is False

    def test_unclassified_limit_kind_is_not_retryable(self) -> None:
        """`limit_kind is None` is the easiest case to get backwards: uncertain classification
        must fail closed, same as a confirmed quota breach."""
        config = BackstopConfig(max_retry_wait_ms=30_000)
        retrying = build_retrying(config)
        exc = BackstopRateLimitError(
            429, "Rate limited", limit_kind=None, retry_after_seconds=0.001
        )

        assert retrying.retry(_retry_state(retrying, exc)) is False

    def test_wait_exceeding_ceiling_is_not_retryable_even_for_concurrency(self) -> None:
        config = BackstopConfig(max_retry_wait_ms=1_000)  # 1 second ceiling
        retrying = build_retrying(config)
        exc = BackstopRateLimitError(
            429,
            "Concurrency limit exceeded",
            limit_kind="concurrency",
            retry_after_seconds=5.0,  # 5s > 1s ceiling
        )

        assert retrying.retry(_retry_state(retrying, exc)) is False

    def test_non_rate_limit_exception_is_not_retryable(self) -> None:
        config = BackstopConfig()
        retrying = build_retrying(config)

        assert retrying.retry(_retry_state(retrying, ValueError("boom"))) is False


class TestBuildRetryingIntegration:
    async def test_succeeds_after_two_concurrency_retries(self) -> None:
        config = BackstopConfig(max_retry_attempts=5, max_retry_wait_ms=30_000)
        retrying = build_retrying(config)
        calls = 0

        async def flaky() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise BackstopRateLimitError(
                    429,
                    "Concurrency limit exceeded",
                    limit_kind="concurrency",
                    retry_after_seconds=0.01,
                )
            return "ok"

        start = time.monotonic()
        result: str = await retrying(flaky)
        elapsed = time.monotonic() - start

        assert result == "ok"
        assert calls == 3
        assert elapsed < 1.0

    async def test_quota_breach_propagates_original_error_immediately(self) -> None:
        config = BackstopConfig(max_retry_attempts=5, max_retry_wait_ms=30_000)
        retrying = build_retrying(config)
        calls = 0

        async def always_quota_limited() -> str:
            nonlocal calls
            calls += 1
            raise BackstopRateLimitError(
                429, "Daily quota exceeded", limit_kind="day", retry_after_seconds=0.01
            )

        start = time.monotonic()
        with pytest.raises(BackstopRateLimitError) as exc_info:
            await retrying(always_quota_limited)
        elapsed = time.monotonic() - start

        assert exc_info.value.limit_kind == "day"
        assert calls == 1
        assert elapsed < 0.5

    async def test_concurrency_breach_exceeding_ceiling_propagates_immediately(self) -> None:
        config = BackstopConfig(max_retry_attempts=5, max_retry_wait_ms=1_000)  # 1s ceiling
        retrying = build_retrying(config)
        calls = 0

        async def always_over_ceiling() -> str:
            nonlocal calls
            calls += 1
            raise BackstopRateLimitError(
                429,
                "Concurrency limit exceeded",
                limit_kind="concurrency",
                retry_after_seconds=5.0,  # 5s > 1s ceiling
            )

        start = time.monotonic()
        with pytest.raises(BackstopRateLimitError) as exc_info:
            await retrying(always_over_ceiling)
        elapsed = time.monotonic() - start

        assert exc_info.value.limit_kind == "concurrency"
        assert calls == 1
        assert elapsed < 0.5
