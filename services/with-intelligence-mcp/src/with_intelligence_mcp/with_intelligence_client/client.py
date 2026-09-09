import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import cast

import httpx
from pydantic import TypeAdapter

from with_intelligence_mcp.metrics import (
    UPSTREAM_RATE_LIMITED,
    UPSTREAM_REQUEST_DURATION,
    UPSTREAM_REQUESTS,
)
from with_intelligence_mcp.with_intelligence_client.credential import CallerSession
from with_intelligence_mcp.with_intelligence_client.errors import (
    ApiError,
    AuthError,
    NotEntitled,
    NotFound,
    RateLimited,
    Unreachable,
)
from with_intelligence_mcp.with_intelligence_client.pagination import Page, parse_page
from with_intelligence_mcp.with_intelligence_client.retry import RetryPolicy
from with_intelligence_mcp.with_intelligence_client.settings import TransportSettings

logger = logging.getLogger(__name__)

type QueryValue = str | int | float | bool | Sequence[str | int]
type Gate = Callable[[str], AbstractAsyncContextManager[None]]

_JSON = TypeAdapter(object)


type Primitive = str | int | float | bool | None


def _flatten(params: Mapping[str, QueryValue]) -> list[tuple[str, Primitive]]:
    """Array filters repeat their key: `?id=1&id=2`. `None` values are dropped by the caller."""
    flat: list[tuple[str, Primitive]] = []
    for key, value in params.items():
        if isinstance(value, (str, int, float, bool)):
            flat.append((key, str(value)))
            continue
        flat.extend((key, str(item)) for item in value)
    return flat


class WithIntelligenceClient:
    """One caller's view of the API, over a pool and gates the factory owns."""

    def __init__(
        self,
        settings: TransportSettings,
        *,
        http_client: Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]],
        gate: Gate,
        retry_policy: RetryPolicy,
        session: CallerSession,
    ) -> None:
        self._settings: TransportSettings = settings
        self._http_client: Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]] = (
            http_client
        )
        self._gate: Gate = gate
        self._retry: RetryPolicy = retry_policy
        self._session: CallerSession = session

    @property
    def settings(self) -> TransportSettings:
        return self._settings

    async def get_json(self, path: str, params: Mapping[str, QueryValue] | None = None) -> object:
        response = await self._request("GET", path, params or {})
        try:
            return _JSON.validate_json(response.content)
        except ValueError as exc:
            raise Unreachable(f"{path} returned a body that is not JSON") from exc

    async def get_page(
        self,
        path: str,
        params: Mapping[str, QueryValue] | None = None,
        *,
        page: int = 1,
        page_size: int | None = None,
    ) -> Page:
        query: dict[str, QueryValue] = dict(params or {})
        query["page"] = page
        query["page_size"] = page_size or self._settings.default_page_size
        return parse_page(await self.get_json(path, query))

    async def iterate(
        self,
        path: str,
        params: Mapping[str, QueryValue] | None = None,
        *,
        max_pages: int = 10,
    ) -> AsyncGenerator[dict[str, object]]:
        """Walk a listing, bounded. `max_pages` exists so a broad filter cannot run away."""
        for page_number in range(1, max_pages + 1):
            page = await self.get_page(path, params, page=page_number)
            for record in page.results:
                yield record
            if not page.has_more:
                return

    async def _request(
        self, method: str, path: str, params: Mapping[str, QueryValue]
    ) -> httpx.Response:
        attempt = 0
        renewed = False
        while True:
            attempt += 1
            try:
                response = await self._send(method, path, params)
                self._raise_for_status(response, path)
                return response
            except AuthError:
                # One renewal per request: the token expired mid-session, or another caller
                # rotated it. A second 401 on a fresh token is a real rejection.
                if renewed:
                    raise
                renewed = True
                _ = await self._session.renewed_access_token()
            except (RateLimited, Unreachable) as error:
                if not self._retry.should_retry(error, attempt):
                    raise
                await asyncio.sleep(self._retry.wait_seconds(error, attempt))

    async def _send(
        self, method: str, path: str, params: Mapping[str, QueryValue]
    ) -> httpx.Response:
        token = await self._session.access_token()
        subject = self._session.subject()
        async with self._gate(subject), self._http_client() as client:
            start = asyncio.get_running_loop().time()
            try:
                response = await client.request(
                    method,
                    path,
                    params=_flatten(params),
                    headers={"authorization": f"Bearer {token}"},
                )
            except httpx.TimeoutException as exc:
                UPSTREAM_REQUESTS.add(1, {"method": method, "outcome": "timeout"})
                raise Unreachable(f"{method} {path} timed out") from exc
            except httpx.RequestError as exc:
                UPSTREAM_REQUESTS.add(1, {"method": method, "outcome": "network_error"})
                raise Unreachable(f"{method} {path} could not be reached") from exc
            finally:
                duration = asyncio.get_running_loop().time() - start
                UPSTREAM_REQUEST_DURATION.record(duration, {"method": method})
        UPSTREAM_REQUESTS.add(1, {"method": method, "outcome": str(response.status_code)})
        return response

    def _raise_for_status(self, response: httpx.Response, path: str) -> None:
        status = response.status_code
        if status < 400:
            return
        if status == 401:
            raise AuthError()
        if status == 403:
            raise NotEntitled(
                f"With Intelligence refused {path} for this account — most likely the data is "
                + "outside its licensed packages or subscription add-ons",
                path=path,
            )
        if status == 404:
            raise NotFound(f"{path} does not exist", path=path)
        if status == 429:
            UPSTREAM_RATE_LIMITED.add(1, {"path": path})
            raise RateLimited(f"{path} is rate-limited", retry_after_seconds=_retry_after(response))
        if status >= 500:
            raise Unreachable(f"{path} returned {status}")
        raise ApiError(f"{path} returned {status}", status_code=status)


def _retry_after(response: httpx.Response) -> float | None:
    raw = cast("object", response.headers.get("retry-after"))
    if not isinstance(raw, str):
        return None
    try:
        return float(raw)
    except ValueError:
        # The header also allows an HTTP date; backoff covers us, so don't parse it.
        return None


def as_query(values: Mapping[str, QueryValue | None]) -> dict[str, QueryValue]:
    """Drop unset filters, so an omitted tool argument does not become `?x=None`."""
    return {key: value for key, value in values.items() if value is not None}


def narrow_dict(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}
