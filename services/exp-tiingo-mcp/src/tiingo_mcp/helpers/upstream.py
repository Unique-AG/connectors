from dataclasses import dataclass

import httpx2
from fastmcp.exceptions import ToolError
from fastmcp.utilities.openapi import parse_openapi_to_http_routes
from fastmcp.utilities.openapi.director import RequestDirector
from jsonschema_path import SchemaPath
from pydantic import TypeAdapter, ValidationError


class UpstreamError(ToolError):
    """An upstream call failed, or its body does not fit the expected model."""


@dataclass(frozen=True)
class Operation[T]:
    """An operationId together with the type its response is parsed into."""

    operation_id: str
    adapter: TypeAdapter[T]


class OperationClient:
    """Calls the operations of an OpenAPI spec and parses the JSON body into the given type."""

    def __init__(self, spec: dict[str, object], http: httpx2.AsyncClient) -> None:
        self._http = http
        self._routes = {
            route.operation_id: route
            for route in parse_openapi_to_http_routes(spec)
            if route.operation_id
        }
        self._director = RequestDirector(SchemaPath.from_dict(spec))

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
        missing = set(route.flat_param_schema.get("required", [])) - given
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
        try:
            response = await self._http.send(request)
            response.raise_for_status()
            return operation.adapter.validate_json(response.content)
        except httpx2.HTTPStatusError as exc:
            url = exc.request.url.copy_with(query=None)
            status = f"{exc.response.status_code} {exc.response.reason_phrase}"
            message = f"{status} for {exc.request.method} {url}"
            body = exc.response.text[:200]
            raise UpstreamError(f"{message}: {body}" if body else message) from exc
        except httpx2.HTTPError as exc:
            raise UpstreamError(str(exc) or type(exc).__name__) from exc
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'body'}: {e['msg']}" for e in exc.errors()
            )
            raise UpstreamError(f"Unexpected response: {problems}") from exc
