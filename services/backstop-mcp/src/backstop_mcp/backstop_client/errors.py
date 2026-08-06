"""Backstop HTTP failures, as typed exceptions.

Layering decision, stated once here because it shapes every module: this service is MCP-only,
so a transport error *is* a tool error. These types subclass `fastmcp.exceptions.ToolError` and
propagate straight to the MCP client with the joined error messages intact, rather than being
translated at a boundary. The cost is that `backstop_client` depends on fastmcp and that
non-tool callers (startup warming, login-form credential verification) can see a `ToolError`;
both already handle their own failures. The benefit is that no tool has to catch-and-rewrap,
and no upstream detail is lost on the way out. `auth.context.NotConnectedError` follows the
same rule.

Exceptions that are *not* meant for the MCP client — `BackstopAuthError`,
`BackstopUnreachableError` in `client.py` — stay plain `Exception`s, because each has a caller
that must react to it (revoke tokens, re-render the login form) rather than surface it.
"""

import re
from dataclasses import dataclass
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
    """One JSON:API error object.

    Backstop is inconsistent: some responses use `detail`, others only `title` (and `code`).
    Both are optional so we can accept either shape.
    """

    detail: str | None = None
    title: str | None = None
    code: str | None = None


class _JsonApiErrorBody(BaseModel):
    errors: list[_JsonApiError]


_ERROR_BODY_ADAPTER = TypeAdapter(_JsonApiErrorBody)


@dataclass(frozen=True, slots=True)
class BackstopErrorDetail:
    """One entry from a Backstop JSON:API `errors[]` array."""

    code: str | None = None
    title: str | None = None
    detail: str | None = None

    @property
    def message(self) -> str | None:
        """Best available human-readable text, preferring `detail` then `title` then `code`."""
        for candidate in (self.detail, self.title, self.code):
            if candidate is not None and (text := candidate.strip()):
                return text
        return None


class BackstopApiError(ToolError):
    """Raised for a Backstop 4xx/5xx response, carrying the JSON:API error(s) verbatim."""

    status_code: int
    detail: str
    code: str | None
    errors: tuple[BackstopErrorDetail, ...]

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str | None = None,
        *,
        errors: tuple[BackstopErrorDetail, ...] = (),
    ) -> None:
        super().__init__(f"Backstop API error ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.errors = errors


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
        errors: tuple[BackstopErrorDetail, ...] = (),
        limit_kind: LimitKind | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(status_code, detail, code, errors=errors)
        self.limit_kind = limit_kind
        self.retry_after_seconds = retry_after_seconds


class BackstopUntrustedUrlError(ToolError):
    """Raised when an upstream-supplied absolute URL points somewhere other than Backstop.

    Pagination follows `links.next` verbatim. Since every request carries
    `Authorization: Basic ...`, a `links.next` pointing at another origin would leak the
    caller's Backstop credential there — so the host is pinned to the configured `base_url`.
    """

    url: str
    expected_host: str

    def __init__(self, url: str, expected_host: str) -> None:
        super().__init__(
            f"Refusing to follow {url!r}: expected host {expected_host!r} (the configured "
            + "Backstop base URL)"
        )
        self.url = url
        self.expected_host = expected_host


class BackstopResponseSchemaError(ToolError):
    """Raised when a successful Backstop response body fails caller-supplied schema validation.

    Unlike `BackstopApiError`, this isn't an HTTP-level failure — the request succeeded,
    but the response body doesn't match the shape the caller expected. Wraps the underlying
    `pydantic.ValidationError` as `cause`, along with the request `path` and `schema_name`,
    so the failure can be logged with enough context to diagnose.
    """

    path: str
    schema_name: str
    cause: ValidationError

    def __init__(self, path: str, schema_name: str, cause: ValidationError) -> None:
        message = (
            f"Backstop response for {path!r} failed schema validation "
            + f"against {schema_name!r}: {cause}"
        )
        super().__init__(message)
        self.path = path
        self.schema_name = schema_name
        self.cause = cause


def _to_error_detail(error: _JsonApiError) -> BackstopErrorDetail:
    return BackstopErrorDetail(code=error.code, title=error.title, detail=error.detail)


def _parse_error_details(response: httpx.Response) -> tuple[BackstopErrorDetail, ...] | None:
    try:
        body = _ERROR_BODY_ADAPTER.validate_json(response.content)
    except ValidationError as exc:
        logger.warning(
            "backstop.error_body.schema_error",
            status_code=response.status_code,
            error=str(exc),
        )
        return None
    if not body.errors:
        return None
    return tuple(_to_error_detail(error) for error in body.errors)


def _join_messages(errors: tuple[BackstopErrorDetail, ...]) -> str | None:
    messages = tuple(message for error in errors if (message := error.message) is not None)
    if not messages:
        return None
    return "; ".join(messages)


def _first_code(errors: tuple[BackstopErrorDetail, ...]) -> str | None:
    for error in errors:
        if error.code is not None and error.code.strip():
            return error.code
    return None


def _fallback_message(response: httpx.Response) -> str:
    logger.debug(
        "backstop.error_body.unparseable",
        status_code=response.status_code,
        body_length=len(response.content),
    )
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
        logger.warning("backstop.retry_after.unparseable", retry_after=retry_after)
        return None


def parse_json_api_error(response: httpx.Response) -> BackstopApiError:
    """Turn a 4xx/5xx `httpx.Response` into the right `BackstopApiError` subclass.

    Parses the full JSON:API `errors[]` body (accepting `detail` and/or `title`), falling back
    to a distinct unparseable-body message rather than crashing on malformed/empty responses.
    429s are further classified into `BackstopRateLimitError` with a best-effort `limit_kind`.
    """
    parsed_errors = _parse_error_details(response) or ()
    joined = _join_messages(parsed_errors)
    detail = joined if joined is not None else _fallback_message(response)
    code = _first_code(parsed_errors)

    if response.status_code == 429:
        limit_kind = _classify_limit_kind(detail, code) if joined is not None else None
        return BackstopRateLimitError(
            response.status_code,
            detail,
            code,
            errors=parsed_errors,
            limit_kind=limit_kind,
            retry_after_seconds=_parse_retry_after(response),
        )

    return BackstopApiError(response.status_code, detail, code, errors=parsed_errors)
