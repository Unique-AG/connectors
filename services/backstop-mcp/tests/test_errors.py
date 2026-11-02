import logging
from datetime import UTC, datetime
from typing import override

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopRateLimitError,
    BackstopResponseSchemaError,
)
from backstop_mcp.features.tasks import TaskAttributes


class TestBackstopResponseSchemaError:
    def test_message_names_the_schema_and_failed_fields_only(self) -> None:
        try:
            TaskAttributes.model_validate({"title": 42, "status": "Open"})
        except ValidationError as exc:
            cause = exc
        else:
            raise AssertionError("expected ValidationError")

        error = BackstopResponseSchemaError(
            "/tasks?filter[entityId][eq]=org-1", "TaskAttributes", cause
        )

        assert error.path == "/tasks?filter[entityId][eq]=org-1"
        assert error.schema_name == "TaskAttributes"
        assert error.cause is cause
        assert str(error) == (
            "Backstop response failed schema validation against 'TaskAttributes' "
            + "at title (string_type, got int)"
        )

    def test_message_lists_ten_failed_fields_and_counts_the_rest(self) -> None:
        try:
            TypeAdapter(list[TaskAttributes]).validate_python([{"title": 1}] * 12)
        except ValidationError as exc:
            cause = exc
        else:
            raise AssertionError("expected ValidationError")

        error = BackstopResponseSchemaError("/tasks", "list[TaskAttributes]", cause)

        assert "9.title (string_type, got int)" in str(error)
        assert "10.title" not in str(error)
        assert str(error).endswith(" and 2 more")


class TestParseJsonApiErrorWellFormed:
    def test_extracts_detail_and_code(self) -> None:
        response = httpx.Response(
            404,
            json={"errors": [{"status": "404", "code": "not_found", "detail": "No such record"}]},
        )

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopApiError)
        assert error.status_code == 404
        assert error.detail == "No such record"
        assert error.code == "not_found"
        assert len(error.errors) == 1
        assert error.errors[0].detail == "No such record"
        assert error.errors[0].code == "not_found"

    def test_ignores_code_when_absent(self) -> None:
        response = httpx.Response(400, json={"errors": [{"detail": "Bad request"}]})

        error = BackstopApiError.from_response(response)

        assert error.detail == "Bad request"
        assert error.code is None
        assert error.errors[0].detail == "Bad request"

    def test_falls_back_to_title_when_detail_absent(self) -> None:
        response = httpx.Response(
            400,
            json={
                "errors": [
                    {
                        "code": "UnsupportedRequestException",
                        "title": "Find all lov-entries is not allowed.",
                    }
                ]
            },
        )

        error = BackstopApiError.from_response(response)

        assert error.detail == "Find all lov-entries is not allowed."
        assert error.code == "UnsupportedRequestException"
        assert error.errors[0].title == "Find all lov-entries is not allowed."
        assert error.errors[0].detail is None

    def test_prefers_detail_over_title(self) -> None:
        response = httpx.Response(
            400,
            json={"errors": [{"title": "Short title", "detail": "Longer detail"}]},
        )

        error = BackstopApiError.from_response(response)

        assert error.detail == "Longer detail"

    def test_joins_all_errors(self) -> None:
        response = httpx.Response(
            400,
            json={
                "errors": [
                    {"code": "a", "detail": "First problem"},
                    {"code": "b", "title": "Second problem"},
                ]
            },
        )

        error = BackstopApiError.from_response(response)

        assert error.detail == "First problem; Second problem"
        assert error.code == "a"
        assert len(error.errors) == 2
        assert error.errors[0].code == "a"
        assert error.errors[1].code == "b"
        assert error.errors[1].message == "Second problem"


class TestParseJsonApiErrorMalformedBody:
    def test_non_json_body_falls_back(self) -> None:
        response = httpx.Response(500, text="not json at all")

        error = BackstopApiError.from_response(response)

        assert error.status_code == 500
        assert error.detail == "Backstop returned status 500 with an unparseable response body"
        assert error.code is None
        assert error.errors == ()

    def test_empty_body_falls_back(self) -> None:
        response = httpx.Response(500)

        error = BackstopApiError.from_response(response)

        assert error.detail == "Backstop returned status 500 with an unparseable response body"
        assert error.errors == ()

    def test_empty_errors_array_falls_back(self) -> None:
        response = httpx.Response(500, json={"errors": []})

        error = BackstopApiError.from_response(response)

        assert error.detail == "Backstop returned status 500 with an unparseable response body"
        assert error.errors == ()

    def test_errors_without_message_fields_fall_back(self) -> None:
        response = httpx.Response(500, json={"errors": [{"status": "500"}]})

        error = BackstopApiError.from_response(response)

        assert error.detail == "Backstop returned status 500 with an unparseable response body"
        assert len(error.errors) == 1
        assert error.errors[0].message is None

    def test_a_body_that_fails_the_error_schema_logs_the_status_but_not_the_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        response = httpx.Response(500, json={"errors": "canary-leak-detail"})

        with caplog.at_level(logging.WARNING):
            BackstopApiError.from_response(response)

        record = next(
            item
            for item in caplog.records
            if item.message == "Backstop error body failed schema validation"
        )
        assert record.__dict__["status_code"] == 500
        assert record.exc_info is not None
        assert "error" not in record.__dict__


class TestParseJsonApiErrorRateLimit:
    def test_recognizes_concurrency_limit_kind(self) -> None:
        response = httpx.Response(429, json={"errors": [{"detail": "Concurrency limit exceeded"}]})

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind == "concurrency"

    def test_recognizes_minute_limit_kind_case_insensitively(self) -> None:
        response = httpx.Response(429, json={"errors": [{"detail": "PER-MINUTE quota hit"}]})

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind == "minute"

    def test_recognizes_limit_kind_from_code(self) -> None:
        response = httpx.Response(
            429, json={"errors": [{"code": "daily_limit", "detail": "Quota exceeded"}]}
        )

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind == "day"

    def test_does_not_misclassify_incidental_day_substring(self) -> None:
        response = httpx.Response(429, json={"errors": [{"detail": "Please try again today"}]})

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind is None

    def test_unrecognizable_body_yields_none_limit_kind(self) -> None:
        response = httpx.Response(429, json={"errors": [{"detail": "Too many requests"}]})

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind is None

    def test_malformed_body_yields_none_limit_kind(self) -> None:
        response = httpx.Response(429, text="not json")

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind is None

    def test_extracts_retry_after_header(self) -> None:
        response = httpx.Response(
            429,
            headers={"Retry-After": "30"},
            json={"errors": [{"detail": "Too many requests"}]},
        )

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.retry_after_seconds == 30.0

    def test_retry_after_absent_yields_none(self) -> None:
        response = httpx.Response(429, json={"errors": [{"detail": "Too many requests"}]})

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.retry_after_seconds is None

    def test_unparseable_retry_after_yields_none(self) -> None:
        response = httpx.Response(
            429,
            headers={"Retry-After": "not-a-number"},
            json={"errors": [{"detail": "Too many requests"}]},
        )

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.retry_after_seconds is None

    def test_unparseable_retry_after_logs_without_the_header_value(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        response = httpx.Response(
            429,
            headers={"Retry-After": "not-a-number"},
            json={"errors": [{"detail": "Too many requests"}]},
        )

        with caplog.at_level(logging.WARNING):
            BackstopApiError.from_response(response)

        record = next(
            item
            for item in caplog.records
            if item.message == "Ignored unparseable Retry-After header"
        )
        assert "not-a-number" not in str(record.__dict__)

    def test_retry_after_http_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            @override
            def now(cls, tz: object = None) -> datetime:
                return now

        monkeypatch.setattr("backstop_mcp.backstop_client.errors.datetime", _FixedDatetime)

        response = httpx.Response(
            429,
            headers={"Retry-After": "Fri, 07 Aug 2026 12:00:30 GMT"},
            json={"errors": [{"detail": "Too many requests"}]},
        )

        error = BackstopApiError.from_response(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.retry_after_seconds == 30.0
