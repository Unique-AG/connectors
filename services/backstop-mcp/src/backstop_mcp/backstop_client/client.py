import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import cast

import httpx

from backstop_mcp.backstop_client.credential import BackstopCredentialSecret
from backstop_mcp.backstop_client.errors import (
    BackstopApiError,
    BackstopAuthError,
    BackstopErrorDetail,
)
from backstop_mcp.backstop_client.pagination import (
    PageResult,
    SinglePage,
    paginate_all,
    parse_page,
)
from backstop_mcp.backstop_client.retry import RetryPolicy
from backstop_mcp.backstop_client.settings import BackstopTransportSettings
from backstop_mcp.backstop_client.utils import (
    T,
    deserialize,
    metric_route,
    resolve_request_url,
)
from backstop_mcp.metrics import (
    BACKSTOP_CONCURRENCY_WAIT,
    BACKSTOP_REQUEST_DURATION,
    BACKSTOP_REQUESTS,
)

logger = logging.getLogger(__name__)

# /reports and /{entity}/{id}/analytics are the calls Backstop docs call out as legitimately
# slow (up to ~30s per 500 records) — they get the extended timeout and the larger
# report-sized page default; everything else gets the ordinary CRUD profile.
_SLOW_ENDPOINT_MARKERS = ("/reports", "/analytics")


def _errors_for_log(errors: tuple[BackstopErrorDetail, ...]) -> list[dict[str, str | None]]:
    return [error.model_dump() for error in errors]


type AuthFailureHook = Callable[[], Awaitable[None]]
type HttpClientProvider = Callable[[], Awaitable[httpx.AsyncClient]]
# Acquired around a *single* upstream request (see `BackstopClient.raw_request`), never around a
# whole tool invocation — Backstop's limit is on concurrent requests, and a caller that holds
# a slot across an elicitation prompt or a batch of gathered calls either starves itself or
# breaches the limit. See `BackstopClientFactory`.
type RequestGate = Callable[[str], AbstractAsyncContextManager[None]]


class BackstopClient:
    """Async wrapper hiding httpx behind `.get/.post/.patch/.delete/.paginate()/.fetch_page()`.

    Built by `BackstopClientFactory` — tool implementations never construct this themselves,
    and never construct settings either (the factory owns the one set translated from config by
    `dependencies.transport_settings`). All cross-cutting concerns — auth headers, the per-user
    concurrency gate, endpoint-aware timeouts, 401/429/error mapping, rate-limit-aware retry,
    metrics — live in `raw_request()`, which every public method funnels through.

    Typed verbs always take a response `schema`. Prefer those for tool/feature code. Use
    `raw_request` only when the body is intentionally ignored (e.g. credential verification) —
    it is not a type-safe substitute for `.get`/`.post`/….
    """

    def __init__(
        self,
        credential: BackstopCredentialSecret,
        settings: BackstopTransportSettings,
        *,
        http_client: HttpClientProvider,
        gate: RequestGate,
        retry_policy: RetryPolicy,
        on_auth_failure: AuthFailureHook | None = None,
    ) -> None:
        self._credential: BackstopCredentialSecret = credential
        self._settings: BackstopTransportSettings = settings
        self._http_client: HttpClientProvider = http_client
        self._gate: RequestGate = gate
        self._retry_policy: RetryPolicy = retry_policy
        self._on_auth_failure: AuthFailureHook | None = on_auth_failure

    async def get(
        self, path: str, *, schema: type[T], params: dict[str, object] | None = None
    ) -> T:
        response = await self.raw_request("GET", path, params=params)
        return self._deserialize(response.content, schema, path=path)

    async def post(self, path: str, *, schema: type[T], json: dict[str, object] | None = None) -> T:
        response = await self.raw_request("POST", path, json=json)
        return self._deserialize(response.content, schema, path=path)

    async def patch(
        self, path: str, *, schema: type[T], json: dict[str, object] | None = None
    ) -> T:
        response = await self.raw_request("PATCH", path, json=json)
        return self._deserialize(response.content, schema, path=path)

    async def delete(self, path: str, *, schema: type[T]) -> T | None:
        response = await self.raw_request("DELETE", path)
        if not response.content:
            return None
        return self._deserialize(response.content, schema, path=path)

    async def paginate(
        self,
        path: str,
        *,
        schema: type[T],
        params: dict[str, object] | None = None,
        max_records: int | None = 10_000,
        page_size: int | None = None,
        parallel: bool = False,
    ) -> PageResult[T]:
        """Read a whole collection, applying `params` (plus a default page size and a zero
        offset) to the first page only — every later page is driven entirely by the literal
        URL/path Backstop returns in `links.next`, which already encodes its own query params.

        Page size defaults to `report_page_size` for the slow report/analytics endpoints and
        `default_page_size` elsewhere; `page_size` overrides both. The parameter *names* come
        from settings (`page_limit_param` / `page_offset_param`) because a wrong name here fails
        silently — Backstop just ignores it and picks its own page size.

        `max_records=None` walks the chain to the end, which is what callers reading a
        complete series (rather than a preview) need. Each page is deserialized as
        `_Page[schema]` in one pass, so a malformed envelope or item on any page fails the
        whole call rather than silently skipping it.

        `parallel=True` requests page two onwards concurrently by offset rather than following
        `links.next` one page at a time, which is a large win on any multi-page collection —
        five requests run in the gate where a serial chain runs one. It relies on
        `meta.totalResourceCount` being a true total, so it is off by default and must only be
        set for endpoints where that holds; see `paginate_all` for what goes wrong when it does
        not.
        """
        first_page_params = dict(params) if params is not None else {}
        limit_param = self._settings.page_limit_param
        offset_param = self._settings.page_offset_param
        if limit_param not in first_page_params:
            first_page_params[limit_param] = (
                page_size if page_size is not None else self._default_page_size(path)
            )
        # Backstop requires the offset to be a multiple of the limit; 0 always satisfies that.
        # Later pages carry their own offset — from `links.next` serially, or from
        # `offset_params` below, which strides by the page size the first page actually
        # returned and sends that size as the limit. Keeping the originally requested
        # limit after a cap would make those offsets illegal.
        if offset_param not in first_page_params:
            first_page_params[offset_param] = 0

        async def fetch_page(
            page_path: str, page_params: dict[str, object] | None
        ) -> httpx.Response:
            return await self.raw_request("GET", page_path, params=page_params)

        def offset_params(offset: int, page_size: int) -> dict[str, object]:
            return {**first_page_params, limit_param: page_size, offset_param: offset}

        return await paginate_all(
            fetch_page=fetch_page,
            first_path=path,
            schema=schema,
            max_records=max_records,
            first_page_params=first_page_params,
            offset_params=offset_params if parallel else None,
        )

    async def fetch_page(
        self,
        path: str,
        *,
        schema: type[T],
        params: dict[str, object] | None = None,
        page_size: int | None = None,
        offset: int = 0,
    ) -> SinglePage[T]:
        """Fetch and parse exactly one page — no `links.next` walk.

        Unlike `.paginate()`, which only fills in the limit/offset params a caller didn't
        already supply, `fetch_page` always sets both from `page_size`/`offset`: the whole
        point of this primitive is that the caller controls the exact page on every call, so
        there is no "first page vs later pages" distinction to preserve.

        Page size defaults the same way `.paginate()`'s does — `report_page_size` for the slow
        report/analytics endpoints, `default_page_size` elsewhere — and the parameter names come
        from settings (`page_limit_param` / `page_offset_param`) for the same reason: a wrong
        name fails silently, since Backstop just ignores an unknown query param.

        The returned `SinglePage.total_count` is `meta.totalResourceCount` verbatim, and is not
        trustworthy on endpoints where a date filter degrades it to a running count rather than
        a true total.
        """
        page_params = dict(params) if params is not None else {}
        page_params[self._settings.page_limit_param] = (
            page_size if page_size is not None else self._default_page_size(path)
        )
        page_params[self._settings.page_offset_param] = offset

        response = await self.raw_request("GET", path, params=page_params)
        return parse_page(response.content, schema, path=path)

    def _deserialize(self, content: bytes, schema: type[T], *, path: str) -> T:
        return cast(T, deserialize(content, schema, path=path))

    def _default_page_size(self, path: str) -> int:
        if any(marker in path for marker in _SLOW_ENDPOINT_MARKERS):
            return self._settings.report_page_size
        return self._settings.default_page_size

    async def raw_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        """Issue a request without deserializing the body.

        Same transport stack as the typed verbs (auth, gate, timeouts, retries, error mapping),
        but returns the raw `httpx.Response`. Do **not** use this for tool/feature code that
        should be type-safe — pass a `schema` to `.get`/`.post`/`.patch`/`.delete`/`.paginate`
        instead. Intended for status-only checks such as credential verification.
        """
        auth = httpx.BasicAuth(
            self._credential.username, self._credential.api_token.get_secret_value()
        )
        timeout = (
            self._settings.reports_timeout_seconds
            if any(marker in path for marker in _SLOW_ENDPOINT_MARKERS)
            else self._settings.default_timeout_seconds
        )
        url = resolve_request_url(self._settings.base_url, path)
        shared_client = await self._http_client()
        retrying = self._retry_policy.build_retrying()
        route = metric_route(path)

        async def make_request() -> httpx.Response:
            # The gate is entered per attempt, and released while a rate-limit backoff sleeps
            # — a retry that held its slot would keep blocking the very concurrency it is
            # waiting to free up.
            waiting_since = time.monotonic()
            async with self._gate(self._credential.username):
                started = time.monotonic()
                BACKSTOP_CONCURRENCY_WAIT.record(started - waiting_since, {"route": route})
                try:
                    response = await shared_client.request(
                        method,
                        url,
                        json=json,
                        params=params,  # pyright: ignore[reportArgumentType]
                        auth=auth,
                        timeout=timeout,
                    )
                finally:
                    BACKSTOP_REQUEST_DURATION.record(
                        time.monotonic() - started, {"method": method, "route": route}
                    )

            BACKSTOP_REQUESTS.add(
                1, {"method": method, "route": route, "status": response.status_code}
            )
            if response.status_code == 401:
                # Always surface BackstopAuthError for 401 — a failing revoke hook must not
                # mask the credential rejection callers need to handle (reconnect).
                if self._on_auth_failure is not None:
                    try:
                        await self._on_auth_failure()
                    except Exception:
                        logger.exception("backstop.auth_failure_hook.failed")
                raise BackstopAuthError(
                    "Backstop rejected the stored credential — please reconnect."
                )
            if response.is_error:
                # Covers 429 too — BackstopApiError.from_response returns a BackstopRateLimitError
                # for those, which the retry predicate in retry.py inspects.
                raise BackstopApiError.from_response(response)
            return response

        logger.debug("backstop.request.start", extra={"method": method, "path": path})
        try:
            response: httpx.Response = await retrying(make_request)
        except BackstopAuthError:
            # A rejected credential is an ordinary outcome rather than a fault — the login form
            # runs this against every password a user types. Logged without a traceback so a
            # typo doesn't read like a transport failure in the console.
            logger.info(
                "backstop.request.unauthorized",
                extra={"method": method, "path": path},
            )
            raise
        except BackstopApiError as exc:
            # Expected upstream failures — surface the full JSON:API `errors[]` in the
            # console without a traceback. Unexpected transport errors still use
            # `logger.exception` below.
            logger.error(
                "backstop.request.failed",
                extra={
                    "method": method,
                    "path": path,
                    "status_code": exc.status_code,
                    "detail": exc.detail,
                    "code": exc.code,
                    "errors": _errors_for_log(exc.errors),
                },
            )
            raise
        except Exception:
            logger.exception(
                "backstop.request.failed",
                extra={"method": method, "path": path},
            )
            raise
        return response
