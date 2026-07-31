import re
from typing import Literal, cast

import httpx
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, TypeAdapter, ValidationError

from backstop_mcp.logging import get_logger

logger = get_logger(__name__)

type LimitKind = Literal["concurrency", "minute", "hour", "day"]

_LIMIT_KIND_KEYWORDS: dict[LimitKind, tuple[str, ...]] = {
    "concurrency": ("concurrency", "concurrent"),
    "minute": ("minute",),
    "hour": ("hour",),
    "day": ("day", "daily"),
}


class _JsonApiError(BaseModel):
    detail: str
    code: str | None = None


class _JsonApiErrorBody(BaseModel):
    errors: list[_JsonApiError]


_ERROR_BODY_ADAPTER = TypeAdapter(_JsonApiErrorBody)


class BackstopApiError(ToolError):
    """Raised for a Backstop 4xx/5xx response, carrying the JSON:API error detail verbatim."""

    status_code: int
    detail: str
    code: str | None

    def __init__(self, status_code: int, detail: str, code: str | None = None) -> None:
        super().__init__(f"Backstop API error ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail
        self.code = code


class BackstopRateLimitError(BackstopApiError):
    """Raised for a Backstop 429, with a best-effort limit classification.

    `limit_kind` is `None` when the body doesn't clearly indicate which limit was breached —
    callers must treat that as non-retryable rather than guess, since retrying against the
    wrong limit (e.g. a daily quota) wastes attempts and won't resolve.
    """

    limit_kind: LimitKind | None
    retry_after_seconds: float | None

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str | None = None,
        *,
        limit_kind: LimitKind | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(status_code, detail, code)
        self.limit_kind = limit_kind
        self.retry_after_seconds = retry_after_seconds


def _parse_error_detail(response: httpx.Response) -> _JsonApiError | None:
    try:
        body = _ERROR_BODY_ADAPTER.validate_json(response.content)
    except ValidationError:
        return None
    if not body.errors:
        return None
    return body.errors[0]


def _fallback_message(response: httpx.Response) -> str:
    logger.debug("backstop.error_body.unparseable", body=response.text)
    return f"Backstop returned status {response.status_code} with an unparseable response body"


def _classify_limit_kind(detail: str, code: str | None) -> LimitKind | None:
    haystack = f"{detail} {code or ''}".lower()
    for kind, keywords in _LIMIT_KIND_KEYWORDS.items():
        if any(
            re.search(rf"(?<![a-z]){re.escape(keyword)}(?![a-z])", haystack) for keyword in keywords
        ):
            return kind
    return None


def _parse_retry_after(response: httpx.Response) -> float | None:
    retry_after = cast("str | None", response.headers.get("Retry-After"))
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except ValueError:
        return None


def parse_json_api_error(response: httpx.Response) -> BackstopApiError:
    """Turn a 4xx/5xx `httpx.Response` into the right `BackstopApiError` subclass.

    Parses the JSON:API `errors[]` body, falling back to a distinct unparseable-body
    message rather than crashing on malformed/empty responses. 429s are further
    classified into `BackstopRateLimitError` with a best-effort `limit_kind`.
    """
    error = _parse_error_detail(response)
    detail = error.detail if error is not None else _fallback_message(response)
    code = error.code if error is not None else None

    if response.status_code == 429:
        limit_kind = _classify_limit_kind(detail, code) if error is not None else None
        return BackstopRateLimitError(
            response.status_code,
            detail,
            code,
            limit_kind=limit_kind,
            retry_after_seconds=_parse_retry_after(response),
        )

    return BackstopApiError(response.status_code, detail, code)
