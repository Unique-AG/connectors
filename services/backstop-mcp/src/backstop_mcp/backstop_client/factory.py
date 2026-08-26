"""Ownership of every process-wide Backstop HTTP resource.

One `BackstopClientFactory` is built by `get_backstop_client_factory` in
`backstop_mcp.dependencies`. It holds the shared connection pool, the per-user
concurrency gates, the one set of transport settings, and the one retry policy — nothing here
re-reads the environment, so what the provider was handed is what every request uses.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx
from pydantic import SecretStr

from backstop_mcp.backstop_client.client import SYSTEM_INFO_PATH, AuthFailureHook, BackstopClient
from backstop_mcp.backstop_client.credential import BackstopCredentialSecret, CallerAuthContext
from backstop_mcp.backstop_client.errors import (
    BackstopApiError,
    BackstopAuthError,
    BackstopUnreachableError,
)
from backstop_mcp.backstop_client.retry import RetryPolicy
from backstop_mcp.backstop_client.settings import BackstopTransportSettings, RetrySettings

logger = logging.getLogger(__name__)

# JSON:API content negotiation + the personal-API-token flag are identical for every user,
# so they're baked in once as shared-client defaults; only `Authorization` varies per call.
_SHARED_CLIENT_HEADERS = {
    "accept": "application/vnd.api+json",
    "content-type": "application/vnd.api+json",
    "token": "true",
}

# Cap on how many per-username gates are retained. Well above any plausible concurrent user
# count for one process; exists only so a long-lived process with high user churn can't grow
# the registry without bound.
_MAX_TRACKED_USERS = 512


@dataclass
class _Gate:
    """One user's concurrency gate, plus the in-flight count used to decide evictability."""

    semaphore: asyncio.Semaphore
    in_flight: int = 0


@dataclass
class _GateRegistry:
    """Per-username request gates enforcing Backstop's hard 5-concurrent-requests-per-user cap.

    Bounded: once over `max_entries`, idle gates (nothing in flight, so no waiter can be
    holding one) are dropped. Evicting a gate is always safe — the next request for that
    username simply creates a fresh one.
    """

    limit: int
    max_entries: int = _MAX_TRACKED_USERS
    _gates: dict[str, _Gate] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @asynccontextmanager
    async def hold(self, username: str) -> AsyncGenerator[None]:
        gate = await self._gate_for(username)
        gate.in_flight += 1
        try:
            async with gate.semaphore:
                yield
        finally:
            gate.in_flight -= 1

    async def _gate_for(self, username: str) -> _Gate:
        async with self._lock:
            gate = self._gates.get(username)
            if gate is None:
                if len(self._gates) >= self.max_entries:
                    self._evict_idle_unlocked()
                gate = _Gate(semaphore=asyncio.Semaphore(self.limit))
                self._gates[username] = gate
            return gate

    def _evict_idle_unlocked(self) -> None:
        idle = [username for username, gate in self._gates.items() if gate.in_flight == 0]
        for username in idle:
            del self._gates[username]
        logger.debug(
            "backstop.gates.evicted",
            extra={"evicted": len(idle), "retained": len(self._gates)},
        )


class BackstopClientFactory:
    """Builds per-caller `BackstopClient`s over one shared pool and one shared set of gates."""

    def __init__(
        self,
        settings: BackstopTransportSettings,
        retry_settings: RetrySettings,
        *,
        auth: CallerAuthContext | None = None,
    ) -> None:
        self._settings: BackstopTransportSettings = settings
        self._auth: CallerAuthContext | None = auth
        self._gates: _GateRegistry = _GateRegistry(limit=settings.max_concurrent_requests_per_user)
        # Built once, here, rather than per request: the predicate and wait strategy are pure
        # closures over immutable settings. See `retry.RetryPolicy` for why the `AsyncRetrying`
        # wrapper it hands out is still per-request.
        self._retry_policy: RetryPolicy = RetryPolicy.from_settings(retry_settings)
        self._http_client: httpx.AsyncClient | None = None
        self._http_client_lock: asyncio.Lock = asyncio.Lock()

    @property
    def settings(self) -> BackstopTransportSettings:
        return self._settings

    def attach_auth(self, auth: CallerAuthContext) -> None:
        """Supply the auth context after construction.

        Needed because the wiring is circular: the auth context's token-revocation hook belongs
        to the OAuth provider, and the provider needs this factory to verify credentials at
        login. Building the factory twice would mean two connection pools, so the cycle is
        broken here instead — one explicit step in `get_backstop_client_factory`
        (`backstop_mcp.dependencies`), rather than a second pool.
        """
        assert self._auth is None, "attach_auth() must be called at most once"
        self._auth = auth

    def for_credential(
        self,
        credential: BackstopCredentialSecret,
        *,
        on_auth_failure: AuthFailureHook | None = None,
        subject: str | None = None,
    ) -> BackstopClient:
        """Build a client authenticated as `credential`.

        Deliberately *not* an async context manager: there is nothing per-client to release.
        Concurrency is gated around each individual request inside `BackstopClient.raw_request`,
        so a caller can hold a client across an elicitation prompt, or fan several requests
        out of one client, without either starving itself or breaching Backstop's limit.
        """
        return BackstopClient(
            credential,
            self._settings,
            http_client=self._shared_http_client,
            gate=self._gates.hold,
            retry_policy=self._retry_policy,
            on_auth_failure=on_auth_failure,
            subject=subject,
        )

    async def for_current_caller(self) -> BackstopClient:
        """Build a client authenticated as the in-flight MCP caller.

        Resolves that caller's own stored credential via the injected `CallerAuthContext` —
        raises `auth.context.NotConnectedError` if they haven't completed the login flow. A
        mid-session Backstop 401 re-checks `/system-info` before revoking; only a confirmed
        rejection revokes their MCP tokens, and that same `/mcp` call then returns HTTP 401.
        """
        assert self._auth is not None, (
            "BackstopClientFactory was built without an auth context; "
            "for_current_caller() needs one to resolve the caller's credential"
        )
        auth = self._auth
        credential = await auth.current_credential()
        return self.for_credential(
            credential,
            on_auth_failure=auth.revoke_current_subject_tokens,
            subject=auth.active_subject(),
        )

    async def verify_credential(self, username: str, api_token: str) -> bool:
        """Check whether a Backstop username + personal API token actually authenticates.

        Called from the login form's submit handler (see `auth/provider.py`) before minting an
        authorization code — there is no stored credential yet, so the caller builds a
        throwaway `BackstopCredentialSecret` and probes via `raw_request` (status only; the
        body is intentionally ignored). Returns True/False for a definite valid/invalid
        answer; raises `BackstopUnreachableError` if Backstop itself couldn't be reached
        (network error, 5xx), which is not the same failure mode as "wrong token" and should be
        shown to the user differently.
        """
        credential = BackstopCredentialSecret(username=username, api_token=SecretStr(api_token))
        client = self.for_credential(credential)
        try:
            await client.raw_request("GET", SYSTEM_INFO_PATH)
        except BackstopAuthError:
            return False
        except BackstopApiError as exc:
            if exc.status_code == 403:
                return False
            raise BackstopUnreachableError(
                f"Backstop returned unexpected status {exc.status_code} "
                + "while verifying credentials"
            ) from exc
        except httpx.RequestError as exc:
            raise BackstopUnreachableError(
                f"Could not reach Backstop at {self._settings.base_url}"
            ) from exc
        return True

    async def aclose(self) -> None:
        """Close the shared connection pool. Wired into the app lifespan."""
        async with self._http_client_lock:
            if self._http_client is not None and not self._http_client.is_closed:
                await self._http_client.aclose()
            self._http_client = None

    async def _shared_http_client(self) -> httpx.AsyncClient:
        # Built lazily rather than in `__init__`: httpx's connection pool binds internal async
        # primitives to whichever event loop is running when it is first used, and `create_app`
        # is called outside any loop. The pool is sized well above the per-user gate because it
        # serves every user of this process.
        async with self._http_client_lock:
            if self._http_client is None or self._http_client.is_closed:
                self._http_client = httpx.AsyncClient(
                    base_url=self._settings.base_url,
                    headers=_SHARED_CLIENT_HEADERS,
                    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                )
            return self._http_client
