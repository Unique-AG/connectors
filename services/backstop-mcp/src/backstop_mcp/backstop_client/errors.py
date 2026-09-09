"""Backstop HTTP failures, as typed exceptions.

Layering decision, stated once here because it shapes every module: this service is MCP-only,
so a transport error *is* a tool error. These types subclass `fastmcp.exceptions.ToolError` and
propagate straight to the MCP client with the joined error messages intact, rather than being
translated at a boundary. The cost is that `backstop_client` depends on fastmcp and that
non-tool callers (startup warming, login-form credential verification) can see a `ToolError`;
both already handle their own failures. The benefit is that no tool has to catch-and-rewrap,
and no upstream detail is lost on the way out. `auth.context.NotConnectedError` follows the
same rule.

`BackstopUnreachableError` stays a plain `Exception` — the login form must re-render, not
surface a tool error. Mid-session 401s split: a re-check that still authenticates raises
`BackstopTransientAuthError` (a `ToolError`, session kept); a re-check that confirms the
credential is dead revokes MCP tokens and raises `BackstopSessionRevokedError`, which the
HTTP middleware turns into 401 so the MCP client reconnects on this call, not the next one.
"""

import logging
import re
from collections.abc import MutableMapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, cast

import httpx
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, TypeAdapter, ValidationError

logger = logging.getLogger(__name__)

type LimitKind = Literal["concurrency", "minute", "hour", "day"]

_LIMIT_KIND_KEYWORDS: dict[LimitKind, tuple[str, ...]] = {
    "concurrency": ("concurrency", "concurrent"),
    "minute": ("minute",),
    "hour": ("hour",),
    "day": ("day", "daily"),
}


class BackstopErrorDetail(BaseModel):
    """One entry from a Backstop JSON:API `errors[]` array.

    Backstop is inconsistent: some responses use `detail`, others only `title` (and `code`).
    Both are optional so we can accept either shape.
    """

    detail: str | None = None
    title: str | None = None
    code: str | None = None

    @property
    def message(self) -> str | None:
        """Best available human-readable text, preferring `detail` then `title` then `code`."""
        for candidate in (self.detail, self.title, self.code):
            if candidate is not None and (text := candidate.strip()):
                return text
        return None


class _JsonApiErrorBody(BaseModel):
    errors: list[BackstopErrorDetail]


_ERROR_BODY_ADAPTER = TypeAdapter(_JsonApiErrorBody)

_BODY_EXCERPT_LIMIT = 500

# Mutable box on the ASGI scope (and a ContextVar of the same object for same-task tests).
# A bool ContextVar cannot cross FastMCP's session task; this object can. See
# `server/session_revoked.py`.
_SESSION_REVOKED_SCOPE_KEY = "backstop_mcp.session_revoked"


@dataclass
class _SessionRevokedFlag:
    revoked: bool = False


_mcp_session_revoked: ContextVar[_SessionRevokedFlag | None] = ContextVar(
    "backstop_mcp_session_revoked", default=None
)


def mark_mcp_session_revoked() -> None:
    """Record that this request's MCP tokens were revoked, so the HTTP response becomes 401."""
    # Production: session task finds the box on FastMCP's current request, not our ContextVar.
    flag = _flag_from_http_request()
    if flag is None:
        # Tests / same-task handlers: no request_ctx, the ContextVar is the box.
        flag = _mcp_session_revoked.get()
    if flag is not None:
        flag.revoked = True


def mcp_session_was_revoked(scope: MutableMapping[str, object] | None = None) -> bool:
    if scope is not None:
        boxed = scope.get(_SESSION_REVOKED_SCOPE_KEY)  # middleware: the box we hung on this request
        return isinstance(boxed, _SessionRevokedFlag) and boxed.revoked
    boxed = _mcp_session_revoked.get()  # no scope: same-task tests that never touch ASGI
    return boxed is not None and boxed.revoked


def reset_mcp_session_revoked(
    scope: MutableMapping[str, object],
) -> Token[_SessionRevokedFlag | None]:
    """Bind a per-request revoke flag to `scope`. Pair with `restore_mcp_session_revoked`.

    Writes to the caller's `scope`, against the house rule on arguments: ASGI gives middleware
    no return path, and a plain dict is what survives the session task's ContextVar snapshot.
    """
    flag = _SessionRevokedFlag()
    scope[_SESSION_REVOKED_SCOPE_KEY] = flag  # cross-task: session reads this via request.scope
    return _mcp_session_revoked.set(flag)  # same-task tests: ContextVar holds the same object


def restore_mcp_session_revoked(token: Token[_SessionRevokedFlag | None]) -> None:
    _mcp_session_revoked.reset(token)


def _flag_from_http_request() -> _SessionRevokedFlag | None:
    """The session task sees this request via `request_ctx`, not the HTTP task's ContextVar."""
    try:
        from fastmcp.server.dependencies import get_http_request

        request = get_http_request()
    except RuntimeError:
        return None  # no HTTP request in this task (unit tests)
    boxed = request.scope.get(_SESSION_REVOKED_SCOPE_KEY)
    return boxed if isinstance(boxed, _SessionRevokedFlag) else None


class BackstopAuthError(Exception):
    """Raised when Backstop rejects the stored credential (401) while calling a real endpoint.

    Login-form verification catches this (a failed `/system-info` probe). Mid-session 401s
    re-check first and then raise `BackstopTransientAuthError` or `BackstopSessionRevokedError`
    instead of this base type, so a single 401 cannot log the user out.
    """


class BackstopTransientAuthError(ToolError):
    """Mid-session 401 that re-verified as still valid. Session kept; the client should retry."""


class BackstopSessionRevokedError(BackstopAuthError):
    """Credential confirmed dead and MCP tokens revoked. The HTTP layer turns this into 401."""

    def __init__(self) -> None:
        mark_mcp_session_revoked()
        super().__init__("Backstop rejected the stored credential — please reconnect.")


class BackstopUnreachableError(Exception):
    """Raised when Backstop can't be reached at all (network error, 5xx) during verification.

    Distinct from "invalid credentials" (401/403) — the caller should show a different
    message ("Backstop is unreachable, try again") rather than blaming the submitted token.
    """


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

    @classmethod
    def from_response(cls, response: httpx.Response) -> BackstopApiError:
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

        return cls(response.status_code, detail, code, errors=parsed_errors)


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
    `Authorization: Basic ...`, a `links.next` pointing at another origin — or the same
    host over a different scheme — would leak the caller's Backstop credential there, so
    scheme and host are pinned to the configured `base_url`.
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


def unauthorized_log_fields(response: httpx.Response, *, secret: str) -> dict[str, object]:
    """Fields for `backstop.request.unauthorized`: parsed JSON:API errors, or a redacted excerpt."""
    fields: dict[str, object] = {"status_code": response.status_code}
    parsed = _parse_error_details(response)
    if parsed is not None:
        first = parsed[0]
        fields["detail"] = first.detail
        fields["title"] = first.title
        fields["code"] = first.code
        return fields
    fields["body_excerpt"] = _body_excerpt(response.content, secret=secret)
    return fields


def _body_excerpt(content: bytes, *, secret: str) -> str:
    text = content.decode("utf-8", errors="replace")
    if secret:
        text = text.replace(secret, "***")
    return text[:_BODY_EXCERPT_LIMIT]


def _parse_error_details(response: httpx.Response) -> tuple[BackstopErrorDetail, ...] | None:
    try:
        body = _ERROR_BODY_ADAPTER.validate_json(response.content)
    except ValidationError as exc:
        logger.warning(
            "backstop.error_body.schema_error",
            extra={"status_code": response.status_code, "error": str(exc)},
        )
        return None
    if not body.errors:
        return None
    return tuple(body.errors)


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
        extra={"status_code": response.status_code, "body_length": len(response.content)},
    )
    return f"Backstop returned status {response.status_code} with an unparseable response body"


def _classify_limit_kind(detail: str, code: str | None) -> LimitKind | None:
    error_text = f"{detail} {code or ''}".lower()
    for kind, keywords in _LIMIT_KIND_KEYWORDS.items():
        if any(
            re.search(rf"(?<![a-z]){re.escape(keyword)}(?![a-z])", error_text)
            for keyword in keywords
        ):
            return kind
    return None


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Parse `Retry-After` as delta-seconds or an HTTP-date (RFC 9110 §10.2.3)."""
    retry_after = cast("str | None", response.headers.get("Retry-After"))
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(retry_after)
    except TypeError, ValueError, IndexError:
        logger.warning(
            "backstop.retry_after.unparseable",
            extra={"retry_after": retry_after},
        )
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    delay = (when - datetime.now(UTC)).total_seconds()
    return max(delay, 0.0)
