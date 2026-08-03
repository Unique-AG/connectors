import asyncio
import base64
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Generic

import httpx
from pydantic import TypeAdapter, ValidationError
from typing_extensions import TypeVar

from backstop_mcp.auth.context import (
    current_subject,
    get_current_backstop_credential,
    revoke_tokens_for_subject,
)
from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.backstop_client.errors import BackstopResponseSchemaError, parse_json_api_error
from backstop_mcp.backstop_client.pagination import (
    PageResult,
    PaginationRequest,
    paginate_all,
)
from backstop_mcp.backstop_client.retry import build_retrying
from backstop_mcp.config import BackstopConfig
from backstop_mcp.logging import get_logger

logger = get_logger(__name__)

_AUTHORIZATION_HEADER = "authorization"
_TOKEN_HEADER = "token"

# GET /system-info takes no parameters and returns no business data — the cheapest real
# Backstop call that still requires a valid credential, so it doubles as a login-time check.
_VERIFICATION_PATH = "/system-info"

type AuthFailureHook = Callable[[], Awaitable[None]]

_DICT_ADAPTER = TypeAdapter(dict[str, object])

# `typing_extensions.TypeVar` (not stdlib) so `T` can carry a PEP 696 default: native PEP 695
# `class Foo[T]:` syntax can't express a default until Python 3.13, but this repo targets 3.12.
# The default lets every schema-less call site (e.g. `GetRequest(path="/system-info")`) infer
# `dict[str, object]` without an explicit subscript, matching today's untyped behavior exactly.
T = TypeVar("T", default=dict[str, object])


@dataclass(frozen=True)
class GetRequest(Generic[T]):
    """Inputs for `BackstopClient.get` — `schema` opts into typed deserialization."""

    path: str
    params: dict[str, object] | None = None
    schema: type[T] | None = None


@dataclass(frozen=True)
class PostRequest(Generic[T]):
    """Inputs for `BackstopClient.post` — `schema` opts into typed deserialization."""

    path: str
    json: dict[str, object] | None = None
    schema: type[T] | None = None


@dataclass(frozen=True)
class PatchRequest(Generic[T]):
    """Inputs for `BackstopClient.patch` — `schema` opts into typed deserialization."""

    path: str
    json: dict[str, object] | None = None
    schema: type[T] | None = None


@dataclass(frozen=True)
class DeleteRequest(Generic[T]):
    """Inputs for `BackstopClient.delete` — `schema` opts into typed deserialization."""

    path: str
    schema: type[T] | None = None


@dataclass(frozen=True)
class PaginateRequest(Generic[T]):
    """Inputs for `BackstopClient.paginate` — `schema` validates each accumulated item."""

    path: str
    params: dict[str, object] | None = None
    max_records: int = 10_000
    schema: type[T] | None = None


def _deserialize(content: bytes, schema: type[T] | None, *, path: str) -> T:
    """Parse a response body, validating against `schema` if given, else the generic dict shape.

    Only the schema-given case gets wrapped as `BackstopResponseSchemaError` — that's the gap
    this closes (today's bare dict validation failure isn't logged at all, since it happens
    after `_request()`'s own try/except). The schema-less path is untouched.
    """
    if schema is None:
        return _DICT_ADAPTER.validate_json(content)  # pyright: ignore[reportReturnType]
    try:
        return TypeAdapter(schema).validate_json(content)
    except ValidationError as exc:
        logger.error("backstop.response.schema_error", path=path, schema=schema.__name__)
        raise BackstopResponseSchemaError(path, schema.__name__, exc) from exc


# /reports and /{entity}/{id}/analytics are the calls Backstop docs call out as legitimately
# slow (up to ~30s per 500 records) — they get the extended timeout and the larger
# report-sized page default; everything else gets the ordinary CRUD profile.
_EXTENDED_PROFILE_MARKERS = ("/reports", "/analytics")

# JSON:API content negotiation + the personal-API-token flag are identical for every user,
# so they're baked in once as shared-client defaults; only `Authorization` varies per call.
_SHARED_CLIENT_HEADERS = {
    "accept": "application/vnd.api+json",
    "content-type": "application/vnd.api+json",
    _TOKEN_HEADER: "true",
}

# Judgment call: Backstop's JSON:API pagination isn't documented against a live instance
# here, but `page[cursor]=...` is the shape already seen in `links.next` (see
# tests/test_pagination.py), so `page[size]` is the most likely sibling param name.
_PAGE_SIZE_PARAM = "page[size]"


class BackstopUnreachableError(Exception):
    """Raised when Backstop can't be reached at all (network error, 5xx) during verification.

    Distinct from "invalid credentials" (401/403) — the caller should show a different
    message ("Backstop is unreachable, try again") rather than blaming the submitted token.
    """


class BackstopAuthError(Exception):
    """Raised when Backstop rejects the stored credential (401) while calling a real endpoint.

    Unlike `BackstopUnreachableError`, this means the credential itself is no longer valid
    (e.g. the user's personal API token was revoked in Backstop) — the caller should prompt
    the user to reconnect rather than retry.
    """


def build_auth_headers(username: str, api_token: str) -> dict[str, str]:
    """Build the `Authorization: Basic ...` + `token: true` headers Backstop expects.

    Every user connects with a personal API token (not a password), so `token: true` is
    always sent — see https://backstopsolutions.elevio.help/en/articles/1018 and .../236.
    """
    basic_auth = base64.b64encode(f"{username}:{api_token}".encode()).decode()
    return {_AUTHORIZATION_HEADER: f"Basic {basic_auth}", _TOKEN_HEADER: "true"}


# --- Shared httpx.AsyncClient, lazily initialized -------------------------------------------
#
# One connection pool serves every Backstop user (only `Authorization` differs per call).
# It's built lazily rather than at import time: httpx's connection pool binds internal
# async primitives to whichever event loop is running when first used, and this test suite
# runs each test function on a fresh event loop — an eagerly-built (or stale, closed) client
# would raise "bound to a different event loop" the next time it's touched.

_shared_client: httpx.AsyncClient | None = None
_shared_client_lock = asyncio.Lock()


async def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    async with _shared_client_lock:
        if _shared_client is None or _shared_client.is_closed:
            _shared_client = httpx.AsyncClient(
                headers=_SHARED_CLIENT_HEADERS,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return _shared_client


# --- Per-username concurrency semaphores ----------------------------------------------------
#
# Backstop hard-limits each user token to `max_concurrent_requests_per_user` concurrent
# connections; the shared client's pool is sized much larger since it serves every user.

_semaphores: dict[str, asyncio.Semaphore] = {}
_semaphores_lock = asyncio.Lock()


async def _get_semaphore(username: str, config: BackstopConfig) -> asyncio.Semaphore:
    async with _semaphores_lock:
        semaphore = _semaphores.get(username)
        if semaphore is None:
            semaphore = asyncio.Semaphore(config.max_concurrent_requests_per_user)
            _semaphores[username] = semaphore
        return semaphore


async def reset_shared_backstop_state_for_tests() -> None:
    """Test-only: drop the shared client, the semaphore registry, and both locks.

    The per-username semaphores and the two module-level locks bind to a running event loop
    on first use exactly like `_shared_client` does (see above) — a `conftest.py` autouse
    fixture calls this between tests so nothing is left bound to a closed loop.
    """
    global _shared_client, _shared_client_lock, _semaphores_lock
    if _shared_client is not None:
        await _shared_client.aclose()
    _shared_client = None
    _shared_client_lock = asyncio.Lock()
    _semaphores.clear()
    _semaphores_lock = asyncio.Lock()


def _is_extended_profile_path(path: str) -> bool:
    return any(marker in path for marker in _EXTENDED_PROFILE_MARKERS)


def _build_url(base_url: str, path: str) -> str:
    return path if path.startswith("http") else base_url.rstrip("/") + path


class BackstopClient:
    """Async-context-managed wrapper hiding httpx behind `.get/.post/.patch/.delete/.paginate()`.

    Built by `create_backstop_client()` (directly, or via `get_backstop_client()` for the
    current MCP caller) — tool implementations never construct this themselves. All
    cross-cutting concerns (auth headers, endpoint-aware timeouts, 401/429/error mapping,
    rate-limit-aware retry) live in `_request()`, which every public method funnels through.
    """

    def __init__(
        self,
        credential: BackstopCredentialSecret,
        config: BackstopConfig,
        on_auth_failure: AuthFailureHook | None,
    ) -> None:
        self._credential: BackstopCredentialSecret = credential
        self._config: BackstopConfig = config
        self._on_auth_failure: AuthFailureHook | None = on_auth_failure

    async def get(self, request: GetRequest[T]) -> T:
        response = await self._request("GET", request.path, params=request.params)
        return _deserialize(response.content, request.schema, path=request.path)

    async def post(self, request: PostRequest[T]) -> T:
        response = await self._request("POST", request.path, json=request.json)
        return _deserialize(response.content, request.schema, path=request.path)

    async def patch(self, request: PatchRequest[T]) -> T:
        response = await self._request("PATCH", request.path, json=request.json)
        return _deserialize(response.content, request.schema, path=request.path)

    async def delete(self, request: DeleteRequest[T]) -> T | None:
        response = await self._request("DELETE", request.path)
        if not response.content:
            return None
        return _deserialize(response.content, request.schema, path=request.path)

    async def paginate(self, request: PaginateRequest[T]) -> PageResult[T]:
        """Walk a `links.next` chain, applying `params` (plus a default page size) to the
        first page only — every later page is driven entirely by the literal URL/path
        Backstop returns, which already encodes its own query params.

        `paginate_all` keeps producing raw `dict[str, object]` items after validating the
        envelope (`links`/`meta`) exactly as before schema support existed; each accumulated
        item is re-validated against `request.schema` here — only if one was given — so a
        malformed item on any page fails the whole call rather than silently skipping it.
        """
        first_page_params = dict(request.params) if request.params is not None else {}
        if _PAGE_SIZE_PARAM not in first_page_params:
            first_page_params[_PAGE_SIZE_PARAM] = (
                self._config.report_page_size
                if _is_extended_profile_path(request.path)
                else self._config.default_page_size
            )

        async def fetch_page(
            page_path: str, page_params: dict[str, object] | None
        ) -> httpx.Response:
            return await self._request("GET", page_path, params=page_params)

        raw_result = await paginate_all(
            PaginationRequest(
                fetch_page=fetch_page,
                first_path=request.path,
                max_records=request.max_records,
                first_page_params=first_page_params,
            )
        )

        if request.schema is None:
            return raw_result  # pyright: ignore[reportReturnType]

        try:
            items = [TypeAdapter(request.schema).validate_python(item) for item in raw_result.items]
        except ValidationError as exc:
            logger.error(
                "backstop.response.schema_error", path=request.path, schema=request.schema.__name__
            )
            raise BackstopResponseSchemaError(request.path, request.schema.__name__, exc) from exc

        return PageResult(
            items=items, total_count=raw_result.total_count, truncated=raw_result.truncated
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        headers = build_auth_headers(
            self._credential.username, self._credential.api_token.get_secret_value()
        )
        timeout = (
            self._config.reports_timeout_seconds
            if _is_extended_profile_path(path)
            else self._config.default_timeout_seconds
        )
        url = _build_url(self._config.base_url, path)
        shared_client = await _get_shared_client()
        retrying = build_retrying(self._config)

        async def make_request() -> httpx.Response:
            response = await shared_client.request(
                method,
                url,
                json=json,
                params=params,  # pyright: ignore[reportArgumentType]
                headers=headers,
                timeout=timeout,
            )
            if response.status_code == 401:
                if self._on_auth_failure is not None:
                    await self._on_auth_failure()
                raise BackstopAuthError(
                    "Backstop rejected the stored credential — please reconnect."
                )
            if response.is_error:
                # Covers 429 too — parse_json_api_error returns a BackstopRateLimitError
                # for those, which the retry predicate in retry.py inspects.
                raise parse_json_api_error(response)
            return response

        logger.debug("backstop.request.start", method=method, path=path)
        try:
            response: httpx.Response = await retrying(make_request)
        except Exception as exc:
            logger.error("backstop.request.failed", method=method, path=path, error=str(exc))
            raise
        return response


@asynccontextmanager
async def create_backstop_client(
    base_url: str,
    credential: BackstopCredentialSecret,
    *,
    on_auth_failure: AuthFailureHook | None = None,
) -> AsyncGenerator[BackstopClient, None]:
    config = BackstopConfig(base_url=base_url)
    semaphore = await _get_semaphore(credential.username, config)
    async with semaphore:
        yield BackstopClient(credential, config, on_auth_failure)


async def get_backstop_client() -> AbstractAsyncContextManager[BackstopClient]:
    """Build a Backstop API client authenticated as the current MCP caller.

    Call this from within a tool implementation, where an authenticated request is active.
    Resolves the caller's own stored credential via `auth.context` — raises
    `auth.context.NotConnectedError` if they haven't completed the login flow. A mid-session
    Backstop 401 also revokes that caller's MCP tokens so the next request forces a re-login.
    """
    credential = await get_current_backstop_credential()
    subject = current_subject()

    async def on_auth_failure() -> None:
        if subject is not None:
            await revoke_tokens_for_subject(subject)

    return create_backstop_client(
        BackstopConfig().base_url, credential, on_auth_failure=on_auth_failure
    )


async def verify_credential(username: str, api_token: str, base_url: str) -> bool:
    """Check whether a Backstop username + personal API token actually authenticates.

    Called from the login form's submit handler (see `auth/provider.py`) before minting an
    authorization code. Returns True/False for a definite valid/invalid answer; raises
    `BackstopUnreachableError` if Backstop itself couldn't be reached (network error, 5xx) —
    that's not the same failure mode as "wrong token" and should be shown to the user
    differently.
    """
    headers = build_auth_headers(username, api_token)

    try:
        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.get(_VERIFICATION_PATH, headers=headers)
    except httpx.RequestError as exc:
        raise BackstopUnreachableError(f"Could not reach Backstop at {base_url}") from exc

    if response.status_code == 200:
        return True
    if response.status_code in (401, 403):
        return False

    raise BackstopUnreachableError(
        f"Backstop returned unexpected status {response.status_code} while verifying credentials"
    )
