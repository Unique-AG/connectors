import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

import httpx
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.backstop_client.credential import BackstopCredentialSecret
from backstop_mcp.backstop_client.errors import (
    BackstopApiError,
    BackstopAuthError,
    BackstopErrorDetail,
    BackstopResponseSchemaError,
    parse_json_api_error,
)
from backstop_mcp.backstop_client.pagination import (
    PageResult,
    PaginationRequest,
    paginate_all,
)
from backstop_mcp.backstop_client.retry import RetryPolicy
from backstop_mcp.backstop_client.settings import BackstopTransportSettings
from backstop_mcp.backstop_client.utils import (
    T,
    build_auth_headers,
    build_url,
    deserialize,
    is_extended_profile_path,
    metric_route,
)
from backstop_mcp.metrics import (
    BACKSTOP_CONCURRENCY_WAIT,
    BACKSTOP_REQUEST_DURATION,
    BACKSTOP_REQUESTS,
)

logger = logging.getLogger(__name__)


def _errors_for_log(errors: tuple[BackstopErrorDetail, ...]) -> list[dict[str, str | None]]:
    return [{"code": error.code, "title": error.title, "detail": error.detail} for error in errors]


type AuthFailureHook = Callable[[], Awaitable[None]]
type HttpClientProvider = Callable[[], Awaitable[httpx.AsyncClient]]
# Resolves a client authenticated as the in-flight MCP caller — in practice
# `BackstopClientFactory.for_current_caller`. Long-lived collaborators that need to call
# Backstop on a caller's behalf (the glossary middleware, the departed-contact detector) take
# this rather than the factory itself, matching how `BackstopClient` receives its own
# collaborators. It resolves the caller's stored credential, so calling it costs a DB read plus
# a decrypt: acquire one only on a path that will actually make a request.
type CallerClientProvider = Callable[[], Awaitable["BackstopClient"]]
# Acquired around a *single* upstream request (see `BackstopClient._request`), never around a
# whole tool invocation — Backstop's limit is on concurrent requests, and a caller that holds
# a slot across an elicitation prompt or a batch of gathered calls either starves itself or
# breaches the limit. See `BackstopClientFactory`.
type RequestGate = Callable[[str], AbstractAsyncContextManager[None]]


class BackstopClient:
    """Async wrapper hiding httpx behind `.get/.post/.patch/.delete/.paginate()`.

    Built by `BackstopClientFactory` — tool implementations never construct this themselves,
    and never construct settings either (the factory owns the one set translated from config by
    `create_app`). All cross-cutting concerns — auth headers, the per-user concurrency gate,
    endpoint-aware timeouts, 401/429/error mapping, rate-limit-aware retry, metrics — live in
    `_request()`, which every public method funnels through.
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
        self, path: str, *, params: dict[str, object] | None = None, schema: type[T] | None = None
    ) -> T:
        response = await self._request("GET", path, params=params)
        return deserialize(response.content, schema, path=path)

    async def post(
        self, path: str, *, json: dict[str, object] | None = None, schema: type[T] | None = None
    ) -> T:
        response = await self._request("POST", path, json=json)
        return deserialize(response.content, schema, path=path)

    async def patch(
        self, path: str, *, json: dict[str, object] | None = None, schema: type[T] | None = None
    ) -> T:
        response = await self._request("PATCH", path, json=json)
        return deserialize(response.content, schema, path=path)

    async def delete(self, path: str, *, schema: type[T] | None = None) -> T | None:
        response = await self._request("DELETE", path)
        if not response.content:
            return None
        return deserialize(response.content, schema, path=path)

    async def paginate(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
        max_records: int | None = 10_000,
        page_size: int | None = None,
        schema: type[T] | None = None,
    ) -> PageResult[T]:
        """Walk a `links.next` chain, applying `params` (plus a default page size and a zero
        offset) to the first page only — every later page is driven entirely by the literal
        URL/path Backstop returns, which already encodes its own query params.

        Page size defaults to `report_page_size` for the slow report/analytics endpoints and
        `default_page_size` elsewhere; `page_size` overrides both. The parameter *names* come
        from settings (`page_limit_param` / `page_offset_param`) because a wrong name here fails
        silently — Backstop just ignores it and picks its own page size.

        `max_records=None` walks the chain to the end, which is what callers reading a
        complete series (rather than a preview) need. `paginate_all` keeps producing raw
        `dict[str, object]` items after validating the envelope (`links`/`meta`/`included`);
        each accumulated item is re-validated against `schema` here — only if one was given —
        so a malformed item on any page fails the whole call rather than silently skipping it.
        """
        first_page_params = dict(params) if params is not None else {}
        limit_param = self._settings.page_limit_param
        offset_param = self._settings.page_offset_param
        if limit_param not in first_page_params:
            first_page_params[limit_param] = (
                page_size if page_size is not None else self._default_page_size(path)
            )
        # Backstop requires the offset to be a multiple of the limit; 0 always satisfies that
        # and every later page comes from `links.next`, which carries its own offset.
        if offset_param not in first_page_params:
            first_page_params[offset_param] = 0

        async def fetch_page(
            page_path: str, page_params: dict[str, object] | None
        ) -> httpx.Response:
            return await self._request("GET", page_path, params=page_params)

        raw_result = await paginate_all(
            PaginationRequest(
                fetch_page=fetch_page,
                first_path=path,
                max_records=max_records,
                first_page_params=first_page_params,
            )
        )

        if schema is None:
            return raw_result  # pyright: ignore[reportReturnType]

        try:
            items = [TypeAdapter(schema).validate_python(item) for item in raw_result.items]
        except ValidationError as exc:
            logger.error(
                "backstop.response.schema_error",
                extra={"path": path, "schema": schema.__name__},
            )
            raise BackstopResponseSchemaError(path, schema.__name__, exc) from exc

        return PageResult(
            items=items,
            included=raw_result.included,
            total_count=raw_result.total_count,
            truncated=raw_result.truncated,
        )

    def _default_page_size(self, path: str) -> int:
        if is_extended_profile_path(path):
            return self._settings.report_page_size
        return self._settings.default_page_size

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
            self._settings.reports_timeout_seconds
            if is_extended_profile_path(path)
            else self._settings.default_timeout_seconds
        )
        url = build_url(self._settings.base_url, path)
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
                        headers=headers,
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

        logger.debug("backstop.request.start", extra={"method": method, "path": path})
        try:
            response: httpx.Response = await retrying(make_request)
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
