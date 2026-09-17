"""Stream one Graph binary response to a file at constant memory.

The SDK cannot do this. Every generated `.get()` on a `$value` endpoint ends in
`send_primitive_async(..., "bytes", ...)`, which reaches `get_http_response_message`
(kiota_http/httpx_request_adapter.py:600) and calls `self._http_client.send(request)` with no
`stream` flag, so httpx reads the whole body into one `bytes` before the adapter is given a chance
to look at it. `ResponseHandlerOption` is not a way round it either: the adapter consults the
handler at :325, twenty-five lines AFTER the body is already buffered.

What is a seam is the request half. `to_get_request_information()` is public on every generated
builder, `set_base_url_for_request_information` and `convert_to_native_async` are public on the
adapter, and `convert_to_native_async` runs the authentication provider itself
(httpx_request_adapter.py:703). So the request that goes on the wire here carries the same bearer
token, the same `Prefer` headers, the same telemetry options and the same middleware pipeline --
retry, redirect and the `/me` URL rewrite included -- as the one the SDK would have sent. Only the
reading of the response is ours.

`_MAX_ERROR_BODY_BYTES` bounds what is read off a failure before it is parsed: a Graph error is an
OData document of a few hundred bytes, and anything past that is a gateway's, not Graph's. The
point of this module is that no response size decides this process's memory, and an error response
is a response. `_ERROR_MAP` restates the blanket entry every generated `$value` builder passes to
the adapter, because `to_get_request_information()` is the only public half of that method and the
error map lives in the other half.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

import httpx
from kiota_abstractions.request_information import RequestInformation
from kiota_abstractions.serialization.parsable_factory import ParsableFactory
from kiota_http.httpx_request_adapter import HttpxRequestAdapter
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.graph_service_client import GraphServiceClient
from opentelemetry import trace

from office_365_mcp.graph_client.errors import (
    GraphResponseTooLarge,
    GraphUnavailable,
    not_graph,
)

_CHUNK_BYTES = 64 * 1024

_MAX_ERROR_BODY_BYTES = 64 * 1024

_ERROR_MAP: dict[str, type[ParsableFactory[ODataError]]] = {"XXX": ODataError}


@dataclass(frozen=True, slots=True)
class Downloaded:
    """A file holding one Graph response body. Valid only inside the `download_to_file` block."""

    path: Path
    size: int
    content_type: str | None


@asynccontextmanager
async def download_to_file(
    client: GraphServiceClient,
    transport: httpx.AsyncClient,
    request_info: RequestInformation,
    *,
    directory: Path,
    max_bytes: int,
) -> AsyncGenerator[Downloaded]:
    """`request_info`'s response body, written to a file under `directory` and deleted after.

    `request_info` is what a generated builder's `to_<verb>_request_information()` returns, so any
    tool reaches any Graph endpoint through this without this module knowing which.

    `max_bytes` is enforced twice: once against `Content-Length` before a byte is read, and again
    against the bytes actually written, because Graph sends chunked responses with no length and a
    length header is the server's claim rather than a measurement.

    The `yield` is wrapped in `not_graph`: the `graph_step` block a caller opens around this call
    is still open while they use the file, and reading a 10 MiB file back to name it is not
    Microsoft's wait to be charged for in `graph_step_duration_seconds`.

    `client.request_adapter` is typed `RequestAdapter[Unknown]`, which spreads a partial type into
    everything it touches, so it is narrowed through `object` to the concrete adapter whose public
    request half this depends on.
    """
    untyped = cast("object", client.request_adapter)
    assert isinstance(untyped, HttpxRequestAdapter), (
        f"streaming needs the httpx adapter's public request half, not {type(untyped).__name__}"
    )
    adapter: HttpxRequestAdapter = untyped

    adapter.set_base_url_for_request_information(request_info)
    request = await adapter.convert_to_native_async(request_info)

    response = await transport.send(request, stream=True)
    try:
        await _raise_for_status(adapter, response)
        _refuse_declared_length(response, max_bytes)
        with NamedTemporaryFile(dir=directory, suffix=".part", delete=True) as handle:
            size = 0
            async for chunk in response.aiter_bytes(_CHUNK_BYTES):
                size += len(chunk)
                if size > max_bytes:
                    raise GraphResponseTooLarge(
                        size=size, limit=max_bytes, declared=_declared_length(response)
                    )
                handle.write(chunk)
            handle.flush()
            _refuse_short_body(response, size)
            with not_graph():
                yield Downloaded(
                    path=Path(handle.name),
                    size=size,
                    content_type=_header(response, "content-type"),
                )
    finally:
        await response.aclose()


async def _raise_for_status(adapter: HttpxRequestAdapter, response: httpx.Response) -> None:
    """Let the SDK classify a failure, from a body it can read.

    TRAP: `throw_failed_responses` cannot be handed the streamed response. It reaches
    `get_root_parse_node`, whose first statement is `payload = response.content`
    (httpx_request_adapter.py:418), and on an unread body httpx raises `ResponseNotRead` --
    which is a `StreamError`, NOT a `TransportError`, so `graph_errors` would file Graph's own
    404 under `error` and answer with a message about this connector's bug.

    So the failure body is read here, bounded, into a response that carries the same status and
    headers and nothing else. That keeps the classification identical to the buffered path:
    `_classify` reads `response_status_code`, `request-id`, `Retry-After` and the OData
    `code`/`innerError.code`, and all of them survive.
    """
    if response.is_success or response.status_code == 304:
        return
    body = bytearray()
    async for chunk in response.aiter_bytes(_CHUNK_BYTES):
        body += chunk[: _MAX_ERROR_BODY_BYTES - len(body)]
        if len(body) >= _MAX_ERROR_BODY_BYTES:
            break
    span = trace.get_current_span()
    await adapter.throw_failed_responses(  # pyright: ignore[reportUnknownMemberType]
        _rebuilt(response, bytes(body)), _ERROR_MAP, span, span
    )


def _rebuilt(response: httpx.Response, body: bytes) -> httpx.Response:
    """`response` with `body` already read. `Content-Length` is dropped: it describes what the
    server said it would send, and httpx computes the header for the bytes actually held."""
    return httpx.Response(
        response.status_code,
        headers=[
            (name, value)
            for name, value in response.headers.multi_items()
            if name.lower() != "content-length"
        ],
        content=body,
        request=response.request,
    )


def _refuse_short_body(response: httpx.Response, size: int) -> None:
    """A body that stopped before the length the server declared is a truncated file.

    Only the streaming path can make this check. `send_primitive_async` returns `response.content`
    and never compares it with the header, so a short `$value` today becomes a `.eml` that opens
    and is missing its last attachment.
    """
    declared = _declared_length(response)
    if declared is not None and size < declared:
        raise GraphUnavailable(
            f"Microsoft Graph sent {size} of the {declared} bytes it declared",
            status=response.status_code,
            code=None,
            request_id=_header(response, "request-id"),
        )


def _refuse_declared_length(response: httpx.Response, max_bytes: int) -> None:
    declared = _declared_length(response)
    if declared is not None and declared > max_bytes:
        raise GraphResponseTooLarge(size=None, limit=max_bytes, declared=declared)


def _declared_length(response: httpx.Response) -> int | None:
    value = _header(response, "content-length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _header(response: httpx.Response, name: str) -> str | None:
    """`httpx.Headers.get` is annotated to return `Any`, which under this project's type checker
    spreads to every field it is assigned to."""
    return cast("str | None", response.headers.get(name))
