"""Shared WI HTTP client resources."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast

import httpx
from pydantic import TypeAdapter

from with_intelligence_mcp.metrics import UPSTREAM_CONCURRENCY_WAIT
from with_intelligence_mcp.with_intelligence_client.credential import (
    CallerSessionProvider,
    WiCredential,
)
from with_intelligence_mcp.with_intelligence_client.errors import (
    AuthenticationRejected,
    RateLimited,
    Unreachable,
)
from with_intelligence_mcp.with_intelligence_client.retry import RetryPolicy
from with_intelligence_mcp.with_intelligence_client.session import WiSession
from with_intelligence_mcp.with_intelligence_client.settings import RetrySettings, TransportSettings

logger = logging.getLogger(__name__)

SIGN_IN_PATH = "/v3/auth/sign-in"
REFRESH_PATH = "/v3/auth/refresh"

_SHARED_HEADERS = {"accept": "application/json", "content-type": "application/json"}

# Bounds the registry for a long-lived process with high user churn.
_MAX_TRACKED_SUBJECTS = 512

_SESSION = TypeAdapter(WiSession)


@dataclass
class _Gate:
    semaphore: asyncio.Semaphore
    active_calls: int = 0


@dataclass
class _GateRegistry:
    """Per-subject request gates. Evicting an idle gate is safe — the next request makes one."""

    limit: int
    max_entries: int = _MAX_TRACKED_SUBJECTS
    _gates: dict[str, _Gate] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @asynccontextmanager
    async def limit_concurrency(self, subject: str) -> AsyncGenerator[None]:
        gate = await self._register_call(subject)
        acquired = False
        try:
            start = asyncio.get_running_loop().time()
            await gate.semaphore.acquire()
            acquired = True
            UPSTREAM_CONCURRENCY_WAIT.record(asyncio.get_running_loop().time() - start)
            yield
        finally:
            if acquired:
                gate.semaphore.release()
            async with self._lock:
                gate.active_calls -= 1

    async def _register_call(self, subject: str) -> _Gate:
        async with self._lock:
            gate = self._gates.get(subject)
            if gate is None:
                if len(self._gates) >= self.max_entries:
                    self._evict_idle_unlocked()
                gate = _Gate(semaphore=asyncio.Semaphore(self.limit))
                self._gates[subject] = gate
            gate.active_calls += 1
            return gate

    def _evict_idle_unlocked(self) -> None:
        idle = [subject for subject, gate in self._gates.items() if gate.active_calls == 0]
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

    def for_session(self, session: CallerSessionProvider) -> WithIntelligenceClient:
        from with_intelligence_mcp.with_intelligence_client.client import WithIntelligenceClient

        return WithIntelligenceClient(
            self._settings,
            http_client=self._borrow_http_client,
            limit_concurrency=self._gates.limit_concurrency,
            retry_policy=self._retry_policy,
            session=session,
        )

    async def sign_in(self, credential: WiCredential) -> WiSession:
        """`POST /v3/auth/sign-in`. Username and password only — no passcode is involved."""
        return await self._request_session(
            SIGN_IN_PATH,
            {
                "username": credential.username,
                "password": credential.password.get_secret_value(),
            },
        )

    async def refresh_session(self, session: WiSession) -> WiSession:
        """Refresh a WI session."""
        return await self._request_session(
            REFRESH_PATH, {"refreshToken": session.refresh_token.get_secret_value()}
        )

    async def _request_session(self, path: str, payload: dict[str, str]) -> WiSession:
        response = await self._send_auth_request(path, payload)

        try:
            return _SESSION.validate_json(response.content)
        except ValueError as exc:
            raise AuthenticationRejected(f"{path} returned an invalid response") from exc

    async def _send_auth_request(self, path: str, payload: dict[str, str]) -> httpx.Response:
        response = await self._post_auth_request(path, payload)
        status = response.status_code
        if status == 200:
            return response
        if status == 429:
            raise RateLimited(
                f"{path} is rate-limited",
                retry_after_seconds=self._retry_policy.parse_retry_after(
                    cast("object", response.headers.get("retry-after"))
                ),
            )
        if status >= 500:
            raise Unreachable(f"{path} returned {status}")
        raise AuthenticationRejected(f"{path} returned {status}")

    async def _post_auth_request(self, path: str, payload: dict[str, str]) -> httpx.Response:
        async with self._borrow_http_client() as client:
            try:
                return await client.post(path, json=payload)
            except httpx.RequestError as exc:
                raise Unreachable(f"could not reach {path}") from exc

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
