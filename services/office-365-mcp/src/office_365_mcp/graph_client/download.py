"""Stream one Graph binary response to a file at constant memory. The SDK buffers every `$value`
body, so this module builds the request with the SDK and reads the response itself."""

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

_RECOMPUTED_PER_BODY = frozenset({"content-length"})

_DESCRIBES_A_BODY_WORTH_PARSING = "content-type"


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
    """`request_info`'s response body, written to a file under `directory` and deleted after."""
    untyped = cast("object", client.request_adapter)
    assert isinstance(untyped, HttpxRequestAdapter), (
        f"this module needs the httpx adapter's public request half, not {type(untyped).__name__}"
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
            _refuse_short_body(response)
            with not_graph():
                yield Downloaded(
                    path=Path(handle.name),
                    size=size,
                    content_type=_header(response, "content-type"),
                )
    finally:
        await response.aclose()


async def _raise_for_status(adapter: HttpxRequestAdapter, response: httpx.Response) -> None:
    """Let the SDK classify a failure, from a body it can read."""
    if response.is_success or response.status_code == 304:
        return
    body = bytearray()
    truncated = False
    async for chunk in response.aiter_bytes(_CHUNK_BYTES):
        body += chunk[: _MAX_ERROR_BODY_BYTES - len(body)]
        if len(body) >= _MAX_ERROR_BODY_BYTES:
            truncated = True
            break
    span = trace.get_current_span()
    await adapter.throw_failed_responses(  # pyright: ignore[reportUnknownMemberType]
        _rebuilt(response, bytes(body), parsable=not truncated), _ERROR_MAP, span, span
    )


def _rebuilt(response: httpx.Response, body: bytes, *, parsable: bool) -> httpx.Response:
    """`response` with `body` already read, as the SDK's classifier wants it."""
    return httpx.Response(
        response.status_code,
        headers=[
            (name, value)
            for name, value in response.headers.multi_items()
            if name.lower() not in _RECOMPUTED_PER_BODY
            and (parsable or name.lower() != _DESCRIBES_A_BODY_WORTH_PARSING)
        ],
        content=body if parsable else b"",
        request=response.request,
    )


def _refuse_short_body(response: httpx.Response) -> None:
    """A body that stopped before the length the server declared is a truncated file."""
    declared = _declared_length(response)
    received = response.num_bytes_downloaded
    if declared is not None and received < declared:
        raise GraphUnavailable(
            f"Microsoft Graph sent {received} of the {declared} bytes it declared",
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
    return cast("str | None", response.headers.get(name))
