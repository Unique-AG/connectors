import asyncio
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import ClassVar, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

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
from with_intelligence_mcp.with_intelligence_client.pagination import Page
from with_intelligence_mcp.with_intelligence_client.retry import RetryPolicy
from with_intelligence_mcp.with_intelligence_client.settings import TransportSettings

type QueryValue = str | int | float | bool | Sequence[str | int]
type Gate = Callable[[str], AbstractAsyncContextManager[None]]

_MAX_ERROR_DETAIL_LENGTH = 500


class _ErrorResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    message: str
    error: str
    status_code: int = Field(alias="statusCode")


_ERROR_RESPONSE = TypeAdapter(_ErrorResponse)


def _metric_path(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment]
    return "/" + "/".join(":id" if segment.isdecimal() else segment for segment in segments)


def _error_message(response: httpx.Response, fallback: str) -> str:
    try:
        error = _ERROR_RESPONSE.validate_json(response.content)
    except ValueError:
        return fallback
    parts = (" ".join(error.error.split()), " ".join(error.message.split()))
    detail = ": ".join(dict.fromkeys(part for part in parts if part))
    if not detail:
        return fallback
    return f"{fallback}: {detail[:_MAX_ERROR_DETAIL_LENGTH]}"


class WithIntelligenceClient:
    """Client for one caller's authenticated WI API requests."""

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
    def asset_class_groups(self) -> tuple[str, ...]:
        return self._settings.asset_class_groups

    async def get_json[T](
        self,
        path: str,
        response_adapter: TypeAdapter[T],
        params: Mapping[str, QueryValue] | None = None,
    ) -> T:
        response = await self._request("GET", path, params or {})
        try:
            return response_adapter.validate_json(response.content)
        except ValueError as exc:
            raise Unreachable(f"{path} returned an invalid response") from exc

    async def get_page[T](
        self,
        path: str,
        response_adapter: TypeAdapter[Page[T]],
        params: Mapping[str, QueryValue] | None = None,
        *,
        page: int = 1,
        page_size: int | None = None,
    ) -> Page[T]:
        query: dict[str, QueryValue] = dict(params or {})
        query["page"] = page
        query["page_size"] = page_size or self._settings.default_page_size
        return await self.get_json(path, response_adapter, query)

    async def iterate[T](
        self,
        path: str,
        response_adapter: TypeAdapter[Page[T]],
        params: Mapping[str, QueryValue] | None = None,
        *,
        max_pages: int = 10,
    ) -> AsyncGenerator[T]:
        """Walk a listing, bounded. `max_pages` exists so a broad filter cannot run away."""
        for page_number in range(1, max_pages + 1):
            page = await self.get_page(path, response_adapter, params, page=page_number)
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
                _ = await self._session.refresh_access_token()
            except (RateLimited, Unreachable) as error:
                retry = self._retry.should_retry(error, attempt)
                if isinstance(error, RateLimited):
                    UPSTREAM_RATE_LIMITED.add(1, {"retried": retry})
                if not retry:
                    raise
                await asyncio.sleep(self._retry.wait_seconds(error, attempt))

    async def _send(
        self, method: str, path: str, params: Mapping[str, QueryValue]
    ) -> httpx.Response:
        token = await self._session.get_access_token()
        subject = self._session.subject()
        metric_path = _metric_path(path)
        async with self._gate(subject), self._http_client() as client:
            start = asyncio.get_running_loop().time()
            try:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    headers={"authorization": f"Bearer {token}"},
                )
            except httpx.TimeoutException as exc:
                UPSTREAM_REQUESTS.add(
                    1, {"method": method, "outcome": "timeout", "path": metric_path}
                )
                raise Unreachable(f"{method} {path} timed out") from exc
            except httpx.RequestError as exc:
                UPSTREAM_REQUESTS.add(
                    1,
                    {"method": method, "outcome": "network_error", "path": metric_path},
                )
                raise Unreachable(f"{method} {path} could not be reached") from exc
            finally:
                duration = asyncio.get_running_loop().time() - start
                UPSTREAM_REQUEST_DURATION.record(duration, {"method": method, "path": metric_path})
        UPSTREAM_REQUESTS.add(
            1,
            {"method": method, "outcome": str(response.status_code), "path": metric_path},
        )
        return response

    def _raise_for_status(self, response: httpx.Response, path: str) -> None:
        status = response.status_code
        if status < 400:
            return
        if status == 401:
            raise AuthError(_error_message(response, "With Intelligence rejected the access token"))
        if status == 403:
            raise NotEntitled(
                _error_message(
                    response,
                    f"With Intelligence refused {path} for this account — most likely the data is "
                    + "outside its licensed packages or subscription add-ons",
                ),
                path=path,
            )
        if status == 404:
            raise NotFound(_error_message(response, f"{path} does not exist"), path=path)
        if status == 429:
            raise RateLimited(
                _error_message(response, f"{path} is rate-limited"),
                retry_after_seconds=self._retry.parse_retry_after(
                    cast("object", response.headers.get("retry-after"))
                ),
            )
        if status >= 500:
            raise Unreachable(_error_message(response, f"{path} returned {status}"))
        raise ApiError(_error_message(response, f"{path} returned {status}"), status_code=status)


def as_query(values: Mapping[str, QueryValue | None]) -> dict[str, QueryValue]:
    """Drop unset filters, so an omitted tool argument does not become `?x=None`."""
    return {key: value for key, value in values.items() if value is not None}
