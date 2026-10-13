import json
from collections.abc import Awaitable, Callable, Mapping

import httpx2

from kyckr_mcp.settings import Settings

UPSTREAM_HEADERS = frozenset(
    {
        "host",
        "content-type",
        "content-length",
        "accept",
        "accept-encoding",
        "connection",
        "user-agent",
    }
)


class KyckrApiError(Exception):
    def __init__(
        self,
        status: int,
        path: str,
        message: str,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.path = path
        self.correlation_id = correlation_id


def _string_field(value: object, key: str) -> str | None:
    if isinstance(value, Mapping):
        field = value.get(key)
        return field if isinstance(field, str) else None
    return None


def _parse_json(raw: str) -> object | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _error_message(body: object | None, status: int, raw: str) -> str:
    if isinstance(body, Mapping):
        data = body.get("data")
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
    return f"{trimmed[:200]}..." if len(trimmed) > 200 else trimmed or f"HTTP {status}"


async def raise_for_kyckr_error(response: httpx2.Response) -> None:
    if response.status_code < 400:
        return
    await response.aread()
    raw = response.text
    body = _parse_json(raw)
    raise KyckrApiError(
        response.status_code,
        response.request.url.path,
        _error_message(body, response.status_code, raw),
        _string_field(body, "correlationId"),
    )


def _request_hook(api_key: str) -> Callable[[httpx2.Request], Awaitable[None]]:
    async def prepare(request: httpx2.Request) -> None:
        for name in list(request.headers):
            if name.lower() not in UPSTREAM_HEADERS:
                del request.headers[name]
        request.headers["Authorization"] = f"Bearer {api_key}"

    return prepare


def create_client(settings: Settings) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=settings.kyckr_base_url,
        timeout=settings.kyckr_timeout_seconds,
        headers={
            "Authorization": f"Bearer {settings.kyckr_api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        event_hooks={
            "request": [_request_hook(settings.kyckr_api_key.get_secret_value())],
            "response": [raise_for_kyckr_error],
        },
    )
