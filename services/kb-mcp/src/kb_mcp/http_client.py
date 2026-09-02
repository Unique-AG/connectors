"""Provide a bounded async HTTP client for unique_sdk."""

import json
import logging
from collections.abc import Mapping
from typing import override

import httpx
import unique_sdk
from unique_sdk import APIConnectionError, HTTPClient, RequestsClient

from kb_mcp.settings import Settings

_LOGGER = logging.getLogger(__name__)

# unique_sdk's own default; kept identical so only pool acquisition changes.
_REQUEST_TIMEOUT_SECONDS = 600.0

_CONNECTION_ERROR_MESSAGE = (
    "Unexpected error communicating with Unique. "
    "If this problem persists, let us know at support@unique.ch"
)

_Result = tuple[bytes, int, Mapping[str, str]]


class PooledHTTPXClient(HTTPClient):
    """Async-only unique_sdk client with a bounded pool."""

    name = "httpx-pooled"

    def __init__(
        self,
        *,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        pool_timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__()

        # Must stay an httpx.Timeout OBJECT. A per-request float would
        # override every field of the client default — including `pool`.
        self._timeout = httpx.Timeout(
            connect=_REQUEST_TIMEOUT_SECONDS,
            read=_REQUEST_TIMEOUT_SECONDS,
            write=_REQUEST_TIMEOUT_SECONDS,
            pool=pool_timeout_seconds,
        )
        # Must be explicit: Limits(max_connections=N) alone leaves it None,
        # and httpcore then keeps N idle sockets instead of httpx's default 20.
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )
        self._client_async = httpx.AsyncClient(
            timeout=self._timeout,
            limits=self._limits,
        )
        self._pool_exhausted = False

    @property
    def pool_exhausted(self) -> bool:
        """Whether a pool acquisition has timed out."""
        return self._pool_exhausted

    @override
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        post_data: object | None = None,
    ) -> _Result:
        raise NotImplementedError(
            "PooledHTTPXClient is async-only; sync requests go through "
            "RequestsClient (see install_pooled_http_client)."
        )

    @override
    async def request_async(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        post_data: object | None = None,
    ) -> _Result:
        try:
            response = await self._client_async.request(
                method,
                url,
                headers=headers,
                content=json.dumps(post_data) if post_data is not None else None,
                timeout=self._timeout,
            )
        except httpx.PoolTimeout as exc:
            self._note_pool_exhausted()
            raise APIConnectionError(
                _CONNECTION_ERROR_MESSAGE,
                http_status=500,
                original_error=exc,
            ) from exc
        except Exception as exc:
            raise APIConnectionError(
                _CONNECTION_ERROR_MESSAGE,
                http_status=500,
                original_error=exc,
            ) from exc
        return response.content, response.status_code, response.headers

    def _note_pool_exhausted(self) -> None:
        if not self._pool_exhausted:
            _LOGGER.error(
                "unique_sdk connection pool exhausted (PoolTimeout); "
                "reporting this pod unhealthy so it is replaced."
            )
        self._pool_exhausted = True

    @override
    def close(self) -> None:
        """No sync client to close; `RequestsClient` owns the sync path."""

    @override
    async def close_async(self) -> None:
        await self._client_async.aclose()


_installed: PooledHTTPXClient | None = None


def install_pooled_http_client(settings: Settings) -> None:
    """Point unique_sdk at the pooled client before its first request."""
    global _installed

    client = PooledHTTPXClient(
        max_connections=settings.http_max_connections,
        max_keepalive_connections=settings.http_max_keepalive_connections,
        pool_timeout_seconds=settings.http_pool_timeout_seconds,
    )
    unique_sdk.default_http_client = RequestsClient(async_fallback_client=client)
    _installed = client


def pool_is_exhausted() -> bool:
    """Whether the outbound pool is known to be unusable. False if uninstalled."""
    return _installed is not None and _installed.pool_exhausted
