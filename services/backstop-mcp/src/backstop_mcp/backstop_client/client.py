import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import NoReturn, cast

import httpx

from backstop_mcp.backstop_client.auth_recheck import (
    TRANSIENT_AUTH_MESSAGE,
    ProbeOutcome,
    RecheckClock,
    confirmed_rejection,
    probe_outcome,
)
from backstop_mcp.backstop_client.credential import CallerSession, CallerSessionProvider
from backstop_mcp.backstop_client.errors import (
    BackstopApiError,
    BackstopAuthError,
    BackstopErrorDetail,
    BackstopSessionRevokedError,
    BackstopTransientAuthError,
    unauthorized_log_fields,
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

# GET /system-info takes no parameters and returns no business data — the cheapest real
# Backstop call that still requires a valid credential. Login verification and mid-session
# 401 re-checks both use it. Keep the path in one place so those two cannot drift.
SYSTEM_INFO_PATH = "/system-info"

# /reports and /{entity}/{id}/analytics are the calls Backstop docs call out as legitimately
# slow (up to ~30s per 500 records) — they get the extended timeout and the larger
# report-sized page default; everything else gets the ordinary CRUD profile.
_SLOW_ENDPOINT_MARKERS = ("/reports", "/analytics")


def _errors_for_log(errors: tuple[BackstopErrorDetail, ...]) -> list[dict[str, str | None]]:
    return [error.model_dump() for error in errors]


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
    metrics — live in `_request()`, which every public method funnels through.

    Holds no credential of its own — it asks `session` who the caller is once per public call
    and threads that `CallerSession` through it. That is what lets the factory hand every
    caller the *same* client object: the one built over the ambient MCP request resolves a
    fresh credential per call, while `for_credential` pins a constant one. Once per public
    call rather than once per HTTP request on purpose — a `paginate()` walking twenty pages
    must not cost twenty credential lookups.

    Typed verbs always take a response `schema`. Prefer those for tool/feature code. Use
    `raw_request` only when the body is intentionally ignored (e.g. credential verification) —
    it is not a type-safe substitute for `.get`/`.post`/….
    """

    def __init__(
        self,
        settings: BackstopTransportSettings,
        *,
        session: CallerSessionProvider,
        http_client: HttpClientProvider,
        gate: RequestGate,
        retry_policy: RetryPolicy,
    ) -> None:
        self._settings: BackstopTransportSettings = settings
        self._session: CallerSessionProvider = session
        self._http_client: HttpClientProvider = http_client
        self._gate: RequestGate = gate
        self._retry_policy: RetryPolicy = retry_policy

    async def get(
        self, path: str, *, schema: type[T], params: dict[str, object] | None = None
    ) -> T:
        response = await self._request(await self._session(), "GET", path, params=params)
        return self._deserialize(response.content, schema, path=path)

    async def post(self, path: str, *, schema: type[T], json: dict[str, object] | None = None) -> T:
        response = await self._request(await self._session(), "POST", path, json=json)
        return self._deserialize(response.content, schema, path=path)

    async def patch(
        self, path: str, *, schema: type[T], json: dict[str, object] | None = None
    ) -> T:
        response = await self._request(await self._session(), "PATCH", path, json=json)
        return self._deserialize(response.content, schema, path=path)

    async def delete(self, path: str, *, schema: type[T]) -> T | None:
        response = await self._request(await self._session(), "DELETE", path)
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
        session = await self._session()
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
            return await self._request(session, "GET", page_path, params=page_params)

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

        response = await self._request(await self._session(), "GET", path, params=page_params)
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
        return await self._request(await self._session(), method, path, json=json, params=params)

    async def _request(
        self,
        session: CallerSession,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        """The whole transport stack for one request, authenticated as `session`."""
        credential = session.credential
        auth = httpx.BasicAuth(credential.username, credential.api_token.get_secret_value())
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
            async with self._gate(credential.username):
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
            # 401 handling is outside the gate: a re-check must not hold the caller's slot, and
            # the first probe waits so in-flight requests can drain.
            if response.status_code == 401:
                await self._handle_unauthorized(session, method, path, response)
            if response.is_error:
                # Covers 429 too — BackstopApiError.from_response returns a BackstopRateLimitError
                # for those, which the retry predicate in retry.py inspects.
                raise BackstopApiError.from_response(response)
            return response

        logger.debug(
            "backstop.request.start", extra=self._log_extra(session, method=method, path=path)
        )
        try:
            response: httpx.Response = await retrying(make_request)
        except (BackstopAuthError, BackstopTransientAuthError):
            # Logged at the 401 site (`backstop.request.unauthorized` / re-check events). A
            # rejected credential is an ordinary outcome rather than a fault, so no traceback.
            raise
        except BackstopApiError as exc:
            # Expected upstream failures — surface the full JSON:API `errors[]` in the
            # console without a traceback. Unexpected transport errors still use
            # `logger.exception` below.
            logger.error(
                "backstop.request.failed",
                extra=self._log_extra(
                    session,
                    method=method,
                    path=path,
                    status_code=exc.status_code,
                    detail=exc.detail,
                    code=exc.code,
                    errors=_errors_for_log(exc.errors),
                ),
            )
            raise
        except Exception:
            logger.exception(
                "backstop.request.failed",
                extra=self._log_extra(session, method=method, path=path),
            )
            raise
        return response

    def _log_extra(self, session: CallerSession, **fields: object) -> dict[str, object]:
        return {
            "username": session.credential.username,
            "subject": session.subject,
            **fields,
        }

    async def _handle_unauthorized(
        self, session: CallerSession, method: str, path: str, response: httpx.Response
    ) -> NoReturn:
        """Log the 401, then either re-check (mid-session) or raise (login verification).

        Always raises. Login verification has no revoke hook and must fail fast. Mid-session
        probes `/system-info` with backoff and only revokes when every probe is unauthorized.
        """
        logger.info(
            "backstop.request.unauthorized",
            extra=self._log_extra(
                session,
                method=method,
                path=path,
                **unauthorized_log_fields(
                    response, secret=session.credential.api_token.get_secret_value()
                ),
            ),
        )
        if session.on_auth_failure is None:
            raise BackstopAuthError("Backstop rejected the stored credential — please reconnect.")
        await self._recheck_then_maybe_revoke(session, trigger_path=path)

    async def _recheck_then_maybe_revoke(
        self, session: CallerSession, *, trigger_path: str
    ) -> NoReturn:
        """Re-probe `/system-info` with backoff; revoke only if every probe is unauthorized."""
        on_auth_failure = session.on_auth_failure
        assert on_auth_failure is not None
        clock = RecheckClock()
        outcomes: list[ProbeOutcome] = []
        while True:
            wait = clock.next_wait()
            if wait is None:
                break
            await asyncio.sleep(wait)
            leftover = clock.leftover()
            if leftover <= 0:
                break
            outcome = await self._probe_system_info(session, budget_seconds=leftover)
            outcomes.append(outcome)
            self._log_recheck_attempt(
                session, trigger_path, clock, attempt=len(outcomes), outcome=outcome
            )
            if outcome == "ok":
                self._raise_transient_auth(session, trigger_path, clock, attempts=len(outcomes))
            if not clock.another_probe_fits():
                break

        if not confirmed_rejection(outcomes):
            self._raise_transient_auth(session, trigger_path, clock, attempts=len(outcomes))
        try:
            # Notify the auth failed an that we need to revoke credentials
            await on_auth_failure()
        except Exception:
            logger.exception("backstop.auth_failure_hook.failed")
            self._log_recheck_decision(
                session, trigger_path, clock, attempts=len(outcomes), revoked=False
            )
            raise BackstopTransientAuthError(TRANSIENT_AUTH_MESSAGE) from None
        self._log_recheck_decision(
            session, trigger_path, clock, attempts=len(outcomes), revoked=True
        )
        raise BackstopSessionRevokedError()

    def _raise_transient_auth(
        self, session: CallerSession, trigger_path: str, clock: RecheckClock, *, attempts: int
    ) -> NoReturn:
        self._log_recheck_decision(session, trigger_path, clock, attempts=attempts, revoked=False)
        raise BackstopTransientAuthError(TRANSIENT_AUTH_MESSAGE)

    def _log_recheck_attempt(
        self,
        session: CallerSession,
        trigger_path: str,
        clock: RecheckClock,
        *,
        attempt: int,
        outcome: ProbeOutcome,
    ) -> None:
        logger.info(
            "backstop.auth_recheck.attempt",
            extra=self._log_extra(
                session,
                trigger_path=trigger_path,
                attempt=attempt,
                outcome=outcome,
                elapsed_ms=clock.elapsed_ms,
            ),
        )

    def _log_recheck_decision(
        self,
        session: CallerSession,
        trigger_path: str,
        clock: RecheckClock,
        *,
        attempts: int,
        revoked: bool,
    ) -> None:
        logger.info(
            "backstop.auth_recheck.decision",
            extra=self._log_extra(
                session,
                trigger_path=trigger_path,
                attempts=attempts,
                elapsed_ms=clock.elapsed_ms,
                revoked=revoked,
            ),
        )

    async def _probe_system_info(
        self, session: CallerSession, *, budget_seconds: float
    ) -> ProbeOutcome:
        """One `/system-info` GET. Must not go through `raw_request`.

        `_request` turns a 401 into this re-check. Probing through it would recurse:
        401 → re-check → probe → 401 → re-check. This path hits httpx itself and only
        classifies the status.
        """
        if budget_seconds <= 0:
            return "error"
        try:
            response = await self._system_info_within(session, budget_seconds)
        except Exception:
            return "error"
        return probe_outcome(response)

    async def _system_info_within(
        self, session: CallerSession, budget_seconds: float
    ) -> httpx.Response:
        """GET `/system-info`; gate wait and HTTP share the leftover re-check window."""
        credential = session.credential
        auth = httpx.BasicAuth(credential.username, credential.api_token.get_secret_value())
        url = resolve_request_url(self._settings.base_url, SYSTEM_INFO_PATH)
        shared_client = await self._http_client()
        route = metric_route(SYSTEM_INFO_PATH)
        deadline = time.monotonic() + budget_seconds
        waiting_since = time.monotonic()
        async with asyncio.timeout(budget_seconds), self._gate(credential.username):
            started = time.monotonic()
            BACKSTOP_CONCURRENCY_WAIT.record(started - waiting_since, {"route": route})
            leftover = deadline - started
            if leftover <= 0:
                raise TimeoutError
            try:
                response = await shared_client.request(
                    "GET",
                    url,
                    auth=auth,
                    timeout=min(self._settings.default_timeout_seconds, leftover),
                )
            finally:
                BACKSTOP_REQUEST_DURATION.record(
                    time.monotonic() - started, {"method": "GET", "route": route}
                )
        BACKSTOP_REQUESTS.add(1, {"method": "GET", "route": route, "status": response.status_code})
        return response
