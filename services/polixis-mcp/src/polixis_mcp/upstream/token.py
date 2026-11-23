"""OAuth 2.0 client-credentials tokens for the Polixis API, from its Keycloak realm.

The client credentials are the MCP's own. A caller's Zitadel token never reaches Polixis.
One token is reused until shortly before it expires, and a 401 fetches another once.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from typing import cast, override

import httpx2
from pydantic import BaseModel
from pydantic import Field
from pydantic import SecretStr

_REFRESH_MARGIN = timedelta(seconds=30)
_UNAUTHORIZED = 401


class _TokenResponse(BaseModel):
    access_token: str = Field(min_length=1)
    expires_in: int = Field(gt=0)


class ClientCredentialsTransport(httpx2.AsyncBaseTransport):
    """Sends each request through `inner` with the bearer token and the API key that Polixis
    wants on every request. A transport rather than an `httpx2.Auth`, which runs before every
    transport, so a request the cache answers fetches no token.
    """

    _inner: httpx2.AsyncBaseTransport
    _client_id: str
    _client_secret: str
    _api_key: str
    _token_url: str
    _timeout: float
    _token_transport: httpx2.AsyncBaseTransport | None
    _now: Callable[[], datetime]
    _lock: asyncio.Lock
    _token: str | None
    _expires_at: datetime | None

    def __init__(
        self,
        inner: httpx2.AsyncBaseTransport,
        *,
        client_id: SecretStr,
        client_secret: SecretStr,
        api_key: SecretStr,
        token_url: str,
        timeout: float,
        token_transport: httpx2.AsyncBaseTransport | None,
        now: Callable[[], datetime],
    ) -> None:
        self._inner = inner
        self._client_id = client_id.get_secret_value()
        self._client_secret = client_secret.get_secret_value()
        self._api_key = api_key.get_secret_value()
        self._token_url = token_url
        self._timeout = timeout
        self._token_transport = token_transport
        self._now = now
        self._lock = asyncio.Lock()
        self._token = None
        self._expires_at = None

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        token = await self._access_token()
        response = await self._inner.handle_async_request(self._signed(request, token=token))
        if response.status_code != _UNAUTHORIZED:
            return response
        await response.aclose()
        renewed = await self._access_token(rejected=token)
        return await self._inner.handle_async_request(self._signed(request, token=renewed))

    @override
    async def aclose(self) -> None:
        await self._inner.aclose()

    def _signed(self, request: httpx2.Request, *, token: str) -> httpx2.Request:
        headers = request.headers.copy()
        headers["x-api-key"] = self._api_key
        headers["Authorization"] = f"Bearer {token}"
        return httpx2.Request(
            request.method,
            request.url,
            headers=headers,
            stream=request.stream,
            extensions=request.extensions,
        )

    async def _access_token(self, *, rejected: str | None = None) -> str:
        """Only the token a 401 rejected is replaced, so concurrent 401s fetch one new token."""
        async with self._lock:
            now = self._now()
            if (
                self._token is not None
                and self._token != rejected
                and self._expires_at is not None
                and now < self._expires_at
            ):
                return self._token
            token = await self._fetch()
            lifetime = timedelta(seconds=token.expires_in)
            self._token = token.access_token
            self._expires_at = now + lifetime - min(_REFRESH_MARGIN, lifetime / 2)
            return self._token

    async def _fetch(self) -> _TokenResponse:
        async with httpx2.AsyncClient(
            transport=self._token_transport, timeout=self._timeout, follow_redirects=False
        ) as http:
            response = await http.post(
                self._token_url,
                headers={"Accept": "application/json"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        response.raise_for_status()
        return _TokenResponse.model_validate(cast(object, response.json()))
