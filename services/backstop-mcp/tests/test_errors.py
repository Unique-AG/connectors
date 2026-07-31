import httpx

from backstop_mcp.backstop_client.errors import (
    BackstopApiError,
    BackstopRateLimitError,
    parse_json_api_error,
)


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

    def test_ignores_code_when_absent(self) -> None:
        response = httpx.Response(400, json={"errors": [{"detail": "Bad request"}]})

        error = parse_json_api_error(response)

        assert error.detail == "Bad request"
        assert error.code is None


class TestParseJsonApiErrorMalformedBody:
    def test_non_json_body_falls_back(self) -> None:
        response = httpx.Response(500, text="not json at all")

        error = parse_json_api_error(response)

        assert error.status_code == 500
        assert error.detail == "Backstop returned status 500 with an unparseable response body"
        assert error.code is None

    def test_empty_body_falls_back(self) -> None:
        response = httpx.Response(500)

        error = parse_json_api_error(response)

        assert error.detail == "Backstop returned status 500 with an unparseable response body"

    def test_empty_errors_array_falls_back(self) -> None:
        response = httpx.Response(500, json={"errors": []})

        error = parse_json_api_error(response)

        assert error.detail == "Backstop returned status 500 with an unparseable response body"

    def test_missing_detail_key_falls_back(self) -> None:
        response = httpx.Response(500, json={"errors": [{"status": "500"}]})

        error = parse_json_api_error(response)

        assert error.detail == "Backstop returned status 500 with an unparseable response body"


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
