import asyncio
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import cast

import httpx2
from fastmcp.exceptions import ToolError
from fastmcp.utilities.openapi import HTTPRoute, parse_openapi_to_http_routes
from fastmcp.utilities.openapi.director import RequestDirector
from jsonschema_path import SchemaPath
from pydantic import TypeAdapter, ValidationError

from mcp_openapi.lock import LockPolicy
from mcp_openapi.retry import DEFAULT_RETRY_POLICY, RetryPolicy


class UpstreamError(ToolError):
    """An upstream call failed, or its body does not fit the expected model."""


class LockTimeoutError(UpstreamError):
    """The lock of the `LockPolicy` was not acquired within its timeout."""


@dataclass(frozen=True)
class Operation[T]:
    """An operationId together with the type its response is parsed into."""

    operation_id: str
    adapter: TypeAdapter[T]


class OperationClient:
    """Calls the operations of an OpenAPI spec and parses the JSON body into the given type.

    `retry_policy` decides which failed responses are sent again. None sends each request once.
    `lock_policy` names a lock held around each attempt. None sends without one.
    """

    def __init__(
        self,
        spec: dict[str, object],
        http: httpx2.AsyncClient,
        *,
        retry_policy: RetryPolicy | None = DEFAULT_RETRY_POLICY,
        lock_policy: LockPolicy | None = None,
    ) -> None:
        self._http: httpx2.AsyncClient = http
        self._retry_policy: RetryPolicy | None = retry_policy
        self._lock_policy: LockPolicy | None = lock_policy
        self._routes: dict[str, HTTPRoute] = {
            route.operation_id: route
            for route in parse_openapi_to_http_routes(spec)
            if route.operation_id
        }
        self._director: RequestDirector = RequestDirector(SchemaPath.from_dict(spec))

    @property
    def operation_ids(self) -> set[str]:
        return set(self._routes)

    async def call[T](self, operation: Operation[T], **arguments: object) -> T:
        """UpstreamError on HTTP or body problems, ValueError on arguments the spec rejects."""
        route = self._routes.get(operation.operation_id)
        assert route is not None, f"operationId {operation.operation_id} is not in the spec"
        unknown = arguments.keys() - route.parameter_map.keys()
        if unknown:
            known = sorted(route.parameter_map)
            raise ValueError(f"{operation.operation_id} has no {sorted(unknown)}, it takes {known}")
        given = {name for name, value in arguments.items() if value not in (None, "")}
        missing = set(cast(list[str], route.flat_param_schema.get("required", []))) - given
        if missing:
            raise ValueError(f"{operation.operation_id} needs {sorted(missing)}")
        built = self._director.build(route, arguments, str(self._http.base_url))
        # Built again through the client so its default headers are merged in.
        request = self._http.build_request(
            built.method,
            built.url.copy_with(query=None),
            params=built.url.params,
            headers=built.headers,
            content=built.read(),
        )
        return self._parse(operation.adapter, await self._send(request))

    async def request_raw[T](
        self,
        method: str,
        path: str,
        schema: type[T],
        *,
        params: Mapping[str, str | int | float | bool] | None = None,
        json: object = None,
    ) -> T:
        """Only for endpoints the spec does not document. Use `call` for every one it does.

        Nothing checks `params` or `json` against the spec, so the upstream is the first to see
        a mistake in them. `path` is relative to the base URL, which keeps the auth on it, and
        anything else is a ValueError.
        """
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError(f"{path} is not a path")
        request = self._http.build_request(method, path, params=params, json=json)
        return self._parse(TypeAdapter(schema), await self._send(request))

    async def _send(self, request: httpx2.Request) -> bytes:
        try:
            if self._retry_policy is None:
                return await self._attempt(request)
            return await self._retry_policy.retrying()(self._attempt, request)
        except httpx2.HTTPStatusError as exc:
            url = exc.request.url.copy_with(query=None)
            status = f"{exc.response.status_code} {exc.response.reason_phrase}"
            message = f"{status} for {exc.request.method} {url}"
            body = exc.response.text[:200]
            raise UpstreamError(f"{message}: {body}" if body else message) from exc
        except httpx2.HTTPError as exc:
            raise UpstreamError(str(exc) or type(exc).__name__) from exc

    async def _attempt(self, request: httpx2.Request) -> bytes:
        async with AsyncExitStack() as held:
            if self._lock_policy is not None:
                await self._acquire(request, held)
            response = await self._http.send(request)
        response.raise_for_status()
        return response.content

    async def _acquire(self, request: httpx2.Request, held: AsyncExitStack) -> None:
        """Only entering the lock is timed, so a slow response does not count against it."""
        policy = self._lock_policy
        assert policy is not None, "_acquire needs a lock policy"
        timeout = policy.acquire_timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                await held.enter_async_context(policy.lock.hold(request))
        except TimeoutError:
            url = request.url.copy_with(query=None)
            message = f"No lock acquired within {timeout}s for {request.method} {url}"
            raise LockTimeoutError(message) from None

    def _parse[T](self, adapter: TypeAdapter[T], content: bytes) -> T:
        try:
            return adapter.validate_json(content)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'body'}: {e['msg']}" for e in exc.errors()
            )
            raise UpstreamError(f"Unexpected response: {problems}") from exc
