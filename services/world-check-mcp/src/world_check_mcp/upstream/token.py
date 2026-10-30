"""OAuth 2.0 client-credentials tokens for the World-Check One API.

The service account is the MCP's own credential. A caller's Zitadel token never reaches LSEG.
One token is reused until shortly before it expires, and a 401 fetches another once.
"""

import asyncio
from base64 import b64encode
from collections.abc import AsyncGenerator, Callable
from datetime import datetime
from datetime import timedelta
from typing import cast, override

import httpx2
from pydantic import SecretStr

_REFRESH_MARGIN = timedelta(seconds=30)


class ServiceAccountAuth(httpx2.Auth):
    """Attaches a bearer token, fetching it from the LSEG token endpoint."""

    _client_id: str
    _client_secret: str
    _token_url: str
    _timeout: float
    _transport: httpx2.AsyncBaseTransport | None
    _now: Callable[[], datetime]
    _lock: asyncio.Lock
    _token: str | None
    _expires_at: datetime | None

    def __init__(
        self,
        client_id: SecretStr,
        client_secret: SecretStr,
        token_url: str,
        *,
        timeout: float,
        transport: httpx2.AsyncBaseTransport | None,
        now: Callable[[], datetime],
    ) -> None:
        self._client_id = client_id.get_secret_value()
        self._client_secret = client_secret.get_secret_value()
        self._token_url = token_url
        self._timeout = timeout
        self._transport = transport
        self._now = now
        self._lock = asyncio.Lock()
        self._token = None
        self._expires_at = None

    @override
    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        token = await self._access_token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code != 401:
            return
        request.headers["Authorization"] = f"Bearer {await self._access_token(rejected=token)}"
        yield request

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
            token, lifetime = await self._fetch()
            margin = min(_REFRESH_MARGIN, lifetime / 2)
            self._token = token
            self._expires_at = now + (lifetime - margin)
            return token

    async def _fetch(self) -> tuple[str, timedelta]:
        async with httpx2.AsyncClient(
            transport=self._transport,
            timeout=self._timeout,
            follow_redirects=False,
        ) as http:
            response = await http.post(
                self._token_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": _basic(self._client_id, self._client_secret),
                },
                data={"grant_type": "client_credentials"},
            )
        response.raise_for_status()
        return _token_body(cast(object, response.json()))


def _basic(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode()
    return f"Basic {b64encode(raw).decode('ascii')}"


def _token_body(payload: object) -> tuple[str, timedelta]:
    if not isinstance(payload, dict):
        raise ValueError("LSEG token response was not a JSON object")
    body = cast(dict[object, object], payload)
    access_token = body.get("access_token")
    expires_in = body.get("expires_in")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("LSEG token response has no access_token")
    if not isinstance(expires_in, int) or isinstance(expires_in, bool) or expires_in <= 0:
        raise ValueError("LSEG token response has no expires_in")
    return access_token, timedelta(seconds=expires_in)
