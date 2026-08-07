from datetime import UTC, datetime

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from backstop_mcp.backstop_client.errors import (
    BackstopApiError,
    BackstopRateLimitError,
    BackstopResponseSchemaError,
    parse_json_api_error,
)


class _Schema(BaseModel):
    name: str


class TestBackstopResponseSchemaError:
    def test_message_includes_path_and_schema_name(self) -> None:
        try:
            _Schema.model_validate({})
        except ValidationError as exc:
            cause = exc
        else:
            raise AssertionError("expected ValidationError")

        error = BackstopResponseSchemaError("/parties/123", _Schema.__name__, cause)

        assert error.path == "/parties/123"
        assert error.schema_name == "_Schema"
        assert error.cause is cause
        assert "/parties/123" in str(error)
        assert "_Schema" in str(error)


class TestParseJsonApiErrorWellFormed:
    def test_extracts_detail_and_code(self) -> None:
        response = httpx.Response(
            404,
            json={"errors": [{"status": "404", "code": "not_found", "detail": "No such record"}]},
        )

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopApiError)
        assert error.status_code == 404
        assert error.detail == "No such record"
        assert error.code == "not_found"
        assert len(error.errors) == 1
        assert error.errors[0].detail == "No such record"
        assert error.errors[0].code == "not_found"

    def test_ignores_code_when_absent(self) -> None:
        response = httpx.Response(400, json={"errors": [{"detail": "Bad request"}]})

        error = parse_json_api_error(response)

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

        error = parse_json_api_error(response)

        assert error.detail == "Find all lov-entries is not allowed."
        assert error.code == "UnsupportedRequestException"
        assert error.errors[0].title == "Find all lov-entries is not allowed."
        assert error.errors[0].detail is None

    def test_prefers_detail_over_title(self) -> None:
        response = httpx.Response(
            400,
            json={"errors": [{"title": "Short title", "detail": "Longer detail"}]},
        )

        error = parse_json_api_error(response)

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

        error = parse_json_api_error(response)

        assert error.detail == "First problem; Second problem"
        assert error.code == "a"
        assert len(error.errors) == 2
        assert error.errors[0].code == "a"
        assert error.errors[1].code == "b"
        assert error.errors[1].message == "Second problem"


class TestParseJsonApiErrorMalformedBody:
    def test_non_json_body_falls_back(self) -> None:
        response = httpx.Response(500, text="not json at all")

        error = parse_json_api_error(response)

        assert error.status_code == 500
        assert error.detail == "Backstop returned status 500 with an unparseable response body"
        assert error.code is None
        assert error.errors == ()

    def test_empty_body_falls_back(self) -> None:
        response = httpx.Response(500)

        error = parse_json_api_error(response)

        assert error.detail == "Backstop returned status 500 with an unparseable response body"
        assert error.errors == ()

    def test_empty_errors_array_falls_back(self) -> None:
        response = httpx.Response(500, json={"errors": []})

        error = parse_json_api_error(response)

        assert error.detail == "Backstop returned status 500 with an unparseable response body"
        assert error.errors == ()

    def test_errors_without_message_fields_fall_back(self) -> None:
        response = httpx.Response(500, json={"errors": [{"status": "500"}]})

        error = parse_json_api_error(response)

        assert error.detail == "Backstop returned status 500 with an unparseable response body"
        assert len(error.errors) == 1
        assert error.errors[0].message is None


class TestParseJsonApiErrorRateLimit:
    def test_recognizes_concurrency_limit_kind(self) -> None:
        response = httpx.Response(429, json={"errors": [{"detail": "Concurrency limit exceeded"}]})

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind == "concurrency"

    def test_recognizes_minute_limit_kind_case_insensitively(self) -> None:
        response = httpx.Response(429, json={"errors": [{"detail": "PER-MINUTE quota hit"}]})

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind == "minute"

    def test_recognizes_limit_kind_from_code(self) -> None:
        response = httpx.Response(
            429, json={"errors": [{"code": "daily_limit", "detail": "Quota exceeded"}]}
        )

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind == "day"

    def test_does_not_misclassify_incidental_day_substring(self) -> None:
        response = httpx.Response(429, json={"errors": [{"detail": "Please try again today"}]})

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind is None

    def test_unrecognizable_body_yields_none_limit_kind(self) -> None:
        response = httpx.Response(429, json={"errors": [{"detail": "Too many requests"}]})

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind is None

    def test_malformed_body_yields_none_limit_kind(self) -> None:
        response = httpx.Response(429, text="not json")

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.limit_kind is None

    def test_extracts_retry_after_header(self) -> None:
        response = httpx.Response(
            429,
            headers={"Retry-After": "30"},
            json={"errors": [{"detail": "Too many requests"}]},
        )

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.retry_after_seconds == 30.0

    def test_retry_after_absent_yields_none(self) -> None:
        response = httpx.Response(429, json={"errors": [{"detail": "Too many requests"}]})

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.retry_after_seconds is None

    def test_unparseable_retry_after_yields_none(self) -> None:
        response = httpx.Response(
            429,
            headers={"Retry-After": "not-a-number"},
            json={"errors": [{"detail": "Too many requests"}]},
        )

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.retry_after_seconds is None

    def test_retry_after_http_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz: object = None) -> datetime:
                return now

        monkeypatch.setattr("backstop_mcp.backstop_client.errors.datetime", _FixedDatetime)

        response = httpx.Response(
            429,
            headers={"Retry-After": "Fri, 07 Aug 2026 12:00:30 GMT"},
            json={"errors": [{"detail": "Too many requests"}]},
        )

        error = parse_json_api_error(response)

        assert isinstance(error, BackstopRateLimitError)
        assert error.retry_after_seconds == 30.0
