import time
from collections.abc import Callable
from typing import Literal, final

import pytest
import tenacity

from backstop_mcp.backstop_client.errors import BackstopRateLimitError
from backstop_mcp.backstop_client.retry import build_retry_policy
from backstop_mcp.backstop_client.settings import RetrySettings


def _retry_state(
    retrying: tenacity.AsyncRetrying, exc: BaseException, attempt_number: int = 1
) -> tenacity.RetryCallState:
    state = tenacity.RetryCallState(retry_object=retrying, fn=None, args=(), kwargs={})
    state.attempt_number = attempt_number
    state.set_exception((type(exc), exc, exc.__traceback__))
    return state


class TestRetryPredicate:
    def test_concurrency_breach_within_ceiling_is_retryable(self) -> None:
        settings = RetrySettings(max_attempts=5, max_wait_ms=30_000)
        retrying = build_retry_policy(settings).build_retrying()
        exc = BackstopRateLimitError(
            429, "Concurrency limit exceeded", limit_kind="concurrency", retry_after_seconds=1.0
        )

        assert retrying.retry(_retry_state(retrying, exc)) is True

    @pytest.mark.parametrize("limit_kind", ["minute", "hour", "day"])
    def test_quota_breach_is_never_retryable_regardless_of_ceiling(
        self, limit_kind: Literal["minute", "hour", "day"]
    ) -> None:
        settings = RetrySettings(max_attempts=5, max_wait_ms=30_000)
        retrying = build_retry_policy(settings).build_retrying()
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
        settings = RetrySettings(max_attempts=5, max_wait_ms=30_000)
        retrying = build_retry_policy(settings).build_retrying()
        exc = BackstopRateLimitError(
            429, "Rate limited", limit_kind=None, retry_after_seconds=0.001
        )

        assert retrying.retry(_retry_state(retrying, exc)) is False

    def test_wait_exceeding_ceiling_is_not_retryable_even_for_concurrency(self) -> None:
        settings = RetrySettings(max_attempts=5, max_wait_ms=1_000)  # 1 second ceiling
        retrying = build_retry_policy(settings).build_retrying()
        exc = BackstopRateLimitError(
            429,
            "Concurrency limit exceeded",
            limit_kind="concurrency",
            retry_after_seconds=5.0,  # 5s > 1s ceiling
        )

        assert retrying.retry(_retry_state(retrying, exc)) is False

    def test_non_rate_limit_exception_is_not_retryable(self) -> None:
        settings = RetrySettings(max_attempts=5, max_wait_ms=30_000)
        retrying = build_retry_policy(settings).build_retrying()

        assert retrying.retry(_retry_state(retrying, ValueError("boom"))) is False


class TestBuildRetryingIntegration:
    async def test_succeeds_after_two_concurrency_retries(self) -> None:
        settings = RetrySettings(max_attempts=5, max_wait_ms=30_000)
        retrying = build_retry_policy(settings).build_retrying()
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
        settings = RetrySettings(max_attempts=5, max_wait_ms=30_000)
        retrying = build_retry_policy(settings).build_retrying()
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
        settings = RetrySettings(max_attempts=5, max_wait_ms=1_000)  # 1s ceiling
        retrying = build_retry_policy(settings).build_retrying()
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


@final
class _StubCounter:
    """Stands in for the OTel counter, recording the attributes each increment carried."""

    def __init__(self, on_add: Callable[[int, dict[str, object] | None], None]) -> None:
        self._on_add: Callable[[int, dict[str, object] | None], None] = on_add

    def add(self, amount: int, attributes: dict[str, object] | None = None) -> None:
        self._on_add(amount, attributes)


class TestRateLimitMetric:
    """The 429 counter existed but nothing ever incremented it, so every rate-limit decision
    the predicate made was invisible in metrics."""

    @staticmethod
    def _recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
        recorded: list[dict[str, object]] = []

        def _add(_amount: int, attributes: dict[str, object] | None = None) -> None:
            recorded.append(dict(attributes or {}))

        # Patched on `retry`, not on `metrics`: the counter is bound into this module at import,
        # so replacing the origin would leave the already-bound reference in place.
        monkeypatch.setattr(
            "backstop_mcp.backstop_client.retry.BACKSTOP_RATE_LIMITED",
            _StubCounter(_add),
        )
        return recorded

    def test_records_a_retried_concurrency_breach(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded = self._recorded(monkeypatch)
        retrying = build_retry_policy(
            RetrySettings(max_attempts=5, max_wait_ms=30_000)
        ).build_retrying()
        exc = BackstopRateLimitError(
            429, "Concurrency limit exceeded", limit_kind="concurrency", retry_after_seconds=1.0
        )

        assert retrying.retry(_retry_state(retrying, exc)) is True
        assert recorded == [{"limit_kind": "concurrency", "retried": True}]

    def test_records_an_unretried_quota_breach(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded = self._recorded(monkeypatch)
        retrying = build_retry_policy(
            RetrySettings(max_attempts=5, max_wait_ms=30_000)
        ).build_retrying()
        exc = BackstopRateLimitError(429, "Daily quota exceeded", limit_kind="day")

        assert retrying.retry(_retry_state(retrying, exc)) is False
        assert recorded == [{"limit_kind": "day", "retried": False}]

    def test_labels_an_unclassifiable_breach_rather_than_dropping_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`limit_kind=None` is the fail-closed case; it still has to be countable."""
        recorded = self._recorded(monkeypatch)
        retrying = build_retry_policy(
            RetrySettings(max_attempts=5, max_wait_ms=30_000)
        ).build_retrying()
        exc = BackstopRateLimitError(429, "Too many requests")

        assert retrying.retry(_retry_state(retrying, exc)) is False
        assert recorded == [{"limit_kind": "unknown", "retried": False}]

    def test_records_a_breach_refused_for_exceeding_the_wait_ceiling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded = self._recorded(monkeypatch)
        retrying = build_retry_policy(
            RetrySettings(max_attempts=5, max_wait_ms=1_000)
        ).build_retrying()
        exc = BackstopRateLimitError(
            429, "Concurrency limit exceeded", limit_kind="concurrency", retry_after_seconds=60.0
        )

        assert retrying.retry(_retry_state(retrying, exc)) is False
        assert recorded == [{"limit_kind": "concurrency", "retried": False}]

    def test_a_non_rate_limit_failure_records_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded = self._recorded(monkeypatch)
        retrying = build_retry_policy(
            RetrySettings(max_attempts=5, max_wait_ms=30_000)
        ).build_retrying()

        assert retrying.retry(_retry_state(retrying, RuntimeError("boom"))) is False
        assert recorded == []


class TestRetryPolicyIsolation:
    def test_each_request_gets_its_own_retrying_wrapper(self) -> None:
        """Tenacity keeps per-call state in a `threading.local()`, which every coroutine on one
        event loop shares — so the wrapper must not be reused across concurrent requests even
        though the policy it comes from is."""
        policy = build_retry_policy(RetrySettings(max_attempts=5, max_wait_ms=30_000))

        assert policy.build_retrying() is not policy.build_retrying()

    def test_the_policy_itself_is_reused(self) -> None:
        policy = build_retry_policy(RetrySettings(max_attempts=5, max_wait_ms=30_000))

        first = policy.build_retrying()
        second = policy.build_retrying()
        assert first.retry is second.retry
        assert first.wait is second.wait
