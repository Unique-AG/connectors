import json
from typing import cast

import httpx2
from mcp_openapi.upstream import UpstreamError

_MAX_RAW_MESSAGE = 200
_TOO_MANY_REQUESTS = 429
_MAX_RETRY_DIGITS = 9


def kyckr_error(error: UpstreamError) -> str:
    """What a failed Kyckr call tells the client: the status, Kyckr's own message and its
    correlationId when Kyckr answered with an error, else the error itself.
    """
    cause = error.__cause__
    if not isinstance(cause, httpx2.HTTPStatusError):
        return f"The call to Kyckr failed: {error}"
    raw = cause.response.text
    body = _parse_json(raw)
    status = cause.response.status_code
    text = f"Kyckr answered {status}: {_error_message(body, status, raw)}"
    text += _retry_hint(cause.response)
    correlation_id = _string_field(body, "correlationId")
    return f"{text}. Correlation id: {correlation_id}" if correlation_id else text


def _retry_hint(response: httpx2.Response) -> str:
    """The `Retry-After` of a 429 as seconds, the only form the old service passed on."""
    seconds = response.headers.get("Retry-After", "")
    if (
        response.status_code == _TOO_MANY_REQUESTS
        and seconds.isascii()
        and seconds.isdigit()
        and len(seconds) <= _MAX_RETRY_DIGITS
    ):
        return f" (retry after {seconds}s)"
    return ""


def _field(value: object, key: str) -> object | None:
    return cast(dict[str, object], value).get(key) if isinstance(value, dict) else None


def _string_field(value: object, key: str) -> str | None:
    field = _field(value, key)
    return field if isinstance(field, str) else None


def _parse_json(raw: str) -> object | None:
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


def _error_message(body: object, status: int, raw: str) -> str:
    data = _field(body, "data")
    message = (
        _string_field(data, "detail")
        or _string_field(data, "title")
        or _string_field(data, "type")
        or _string_field(body, "message")
        or _string_field(body, "detail")
        or _string_field(body, "title")
        or _string_field(body, "details")
    )
    if message:
        return message
    trimmed = raw.strip()
    if len(trimmed) > _MAX_RAW_MESSAGE:
        return f"{trimmed[:_MAX_RAW_MESSAGE]}..."
    return trimmed or f"HTTP {status}"
