"""Ownership of every process-wide HTTP resource: one pool, one gate registry, one retry policy.

Nothing here re-reads the environment — what the provider was handed is what every request uses.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast

import httpx
from pydantic import TypeAdapter

from with_intelligence_mcp.with_intelligence_client.credential import (
    CallerSession,
    WiCredential,
)
from with_intelligence_mcp.with_intelligence_client.errors import (
    RateLimited,
    SignInFailed,
    Unreachable,
)
from with_intelligence_mcp.with_intelligence_client.retry import RetryPolicy, parse_retry_after
from with_intelligence_mcp.with_intelligence_client.session import WiSession
from with_intelligence_mcp.with_intelligence_client.settings import RetrySettings, TransportSettings

logger = logging.getLogger(__name__)

SIGN_IN_PATH = "/v3/auth/sign-in"
REFRESH_PATH = "/v3/auth/refresh"

_SHARED_HEADERS = {"accept": "application/json", "content-type": "application/json"}

# Bounds the registry for a long-lived process with high user churn.
_MAX_TRACKED_SUBJECTS = 512

_JSON = TypeAdapter(object)


@dataclass
class _Gate:
    semaphore: asyncio.Semaphore
    in_flight: int = 0


@dataclass
class _GateRegistry:
    """Per-subject request gates. Evicting an idle gate is safe — the next request makes one."""

    limit: int
    max_entries: int = _MAX_TRACKED_SUBJECTS
    _gates: dict[str, _Gate] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @asynccontextmanager
    async def hold(self, subject: str) -> AsyncGenerator[None]:
        gate = await self._gate_for(subject)
        gate.in_flight += 1
        try:
            async with gate.semaphore:
                yield
        finally:
            gate.in_flight -= 1

    async def _gate_for(self, subject: str) -> _Gate:
        async with self._lock:
            gate = self._gates.get(subject)
            if gate is None:
                if len(self._gates) >= self.max_entries:
                    self._evict_idle_unlocked()
                gate = _Gate(semaphore=asyncio.Semaphore(self.limit))
                self._gates[subject] = gate
            return gate

    def _evict_idle_unlocked(self) -> None:
        idle = [subject for subject, gate in self._gates.items() if gate.in_flight == 0]
        for subject in idle:
            del self._gates[subject]


class WithIntelligenceClientFactory:
    """Builds per-caller clients over one shared pool, and performs the two auth calls."""

    def __init__(self, settings: TransportSettings, retry_settings: RetrySettings) -> None:
        self._settings: TransportSettings = settings
        self._gates: _GateRegistry = _GateRegistry(limit=settings.max_concurrent_requests_per_user)
        self._retry_policy: RetryPolicy = RetryPolicy.from_settings(retry_settings)
        self._http_client: httpx.AsyncClient | None = None
        self._http_client_lock: asyncio.Lock = asyncio.Lock()

    @property
    def settings(self) -> TransportSettings:
        return self._settings

    def for_session(self, session: CallerSession) -> WithIntelligenceClient:
        from with_intelligence_mcp.with_intelligence_client.client import WithIntelligenceClient

        return WithIntelligenceClient(
            self._settings,
            http_client=self._borrow_http_client,
            gate=self._gates.hold,
            retry_policy=self._retry_policy,
            session=session,
        )

    async def sign_in(self, credential: WiCredential) -> WiSession:
        """`POST /v3/auth/sign-in`. Username and password only — no passcode is involved."""
        return await self._auth_call(
            SIGN_IN_PATH,
            {
                "username": credential.username,
                "password": credential.password.get_secret_value(),
            },
        )

    async def refresh(self, session: WiSession) -> WiSession:
        """`POST /v3/auth/refresh`.

        With Intelligence may or may not rotate the refresh token here; whatever comes back is
        stored, so both behaviours are handled without knowing which it is.
        """
        return await self._auth_call(
            REFRESH_PATH, {"refreshToken": session.refresh_token.get_secret_value()}
        )

    async def _auth_call(self, path: str, payload: dict[str, str]) -> WiSession:
        from datetime import UTC, datetime

        response = await self._auth_response(path, payload)

        try:
            body = _JSON.validate_json(response.content)
        except ValueError as exc:
            raise SignInFailed(f"{path} returned a body that is not JSON") from exc
        if not isinstance(body, dict):
            raise SignInFailed(f"{path} returned {type(body).__name__}, expected an object")

        fields = cast(dict[str, object], body)
        access, refresh = fields.get("accessToken"), fields.get("refreshToken")
        if not isinstance(access, str) or not isinstance(refresh, str):
            raise SignInFailed(f"{path} returned no accessToken/refreshToken")
        return WiSession.model_validate(
            {"access_token": access, "refresh_token": refresh, "issued_at": datetime.now(UTC)}
        )

    async def _auth_response(self, path: str, payload: dict[str, str]) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._post_auth(path, payload)
                self._raise_for_auth_status(response, path)
                return response
            except (RateLimited, Unreachable) as error:
                if not self._retry_policy.should_retry(error, attempt):
                    raise
                await asyncio.sleep(self._retry_policy.wait_seconds(error, attempt))

    async def _post_auth(self, path: str, payload: dict[str, str]) -> httpx.Response:
        async with self._borrow_http_client() as client:
            try:
                return await client.post(path, json=payload)
            except httpx.RequestError as exc:
                raise Unreachable(f"could not reach {path}") from exc

    def _raise_for_auth_status(self, response: httpx.Response, path: str) -> None:
        status = response.status_code
        if status == 200:
            return
        if status == 429:
            raise RateLimited(
                f"{path} is rate-limited",
                retry_after_seconds=parse_retry_after(
                    cast("object", response.headers.get("retry-after"))
                ),
            )
        if status >= 500:
            raise Unreachable(f"{path} returned {status}")
        raise SignInFailed(f"{path} returned {status}")

    async def aclose(self) -> None:
        async with self._http_client_lock:
            if self._http_client is not None and not self._http_client.is_closed:
                await self._http_client.aclose()
            self._http_client = None

    @asynccontextmanager
    async def _borrow_http_client(self) -> AsyncGenerator[httpx.AsyncClient]:
        """Yields the shared client without closing it — the lifespan owns that."""
        yield await self._shared_http_client()

    async def _shared_http_client(self) -> httpx.AsyncClient:
        # Lazily: httpx binds its pool to whichever loop first uses it, and `create_app` runs
        # outside any loop.
        async with self._http_client_lock:
            if self._http_client is None or self._http_client.is_closed:
                self._http_client = httpx.AsyncClient(
                    base_url=self._settings.base_url,
                    headers=_SHARED_HEADERS,
                    timeout=self._settings.default_timeout_seconds,
                    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                )
            return self._http_client


from with_intelligence_mcp.with_intelligence_client.client import (  # noqa: E402
    WithIntelligenceClient,
)
