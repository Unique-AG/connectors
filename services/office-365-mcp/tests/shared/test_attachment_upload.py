"""Every payload in this file is synthetic data. No attachment in this file ever reaches a
real message. `attachment-upload.invalid` is not a real Microsoft host. It replaces the
pre-authenticated `uploadUrl` value that `createUploadSession` returns.
"""

from collections.abc import Sequence
from typing import cast

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphFailure
from office_365_mcp.shared.attachment_upload import UPLOAD_CHUNK_BYTES, upload_attachment
from office_365_mcp.shared.mail import MAX_ATTACHMENT_BYTES

_MESSAGE_ID = "AAMkAGI2SYNTHETIC-draft-0001="

_MESSAGES = "/me/messages"

_SHARED_MESSAGES = "/users/shared@example.invalid/messages"

_UPLOAD_URL = "https://attachment-upload.invalid/session/abc?authtoken=synthetic"

_NAME = "budget.pdf"

_CONTENT_TYPE = "application/pdf"


def _bytes(size: int) -> bytes:
    return b"a" * size


def _session_route(graph: respx.MockRouter, *, base: str = _MESSAGES) -> respx.Route:
    return graph.post(f"{base}/{_MESSAGE_ID}/attachments/createUploadSession").mock(
        return_value=httpx.Response(
            201,
            json={
                "uploadUrl": _UPLOAD_URL,
                "expirationDateTime": "2026-09-24T00:00:00Z",
                "nextExpectedRanges": ["0-"],
            },
        )
    )


def _inline_route(graph: respx.MockRouter, *, base: str = _MESSAGES) -> respx.Route:
    return graph.post(f"{base}/{_MESSAGE_ID}/attachments").mock(
        return_value=httpx.Response(
            201,
            json={
                "@odata.type": "#microsoft.graph.fileAttachment",
                "id": "AAMkAGI2SYNTHETIC-attachment-0001=",
                "name": _NAME,
                "contentType": _CONTENT_TYPE,
                "size": 42,
            },
        )
    )


async def _upload(
    client: GraphServiceClient,
    transport: httpx.AsyncClient,
    *,
    content: bytes,
    mailbox: str | None = None,
) -> None:
    await upload_attachment(
        client,
        transport,
        mailbox=mailbox,
        message_id=_MESSAGE_ID,
        name=_NAME,
        content_type=_CONTENT_TYPE,
        content=content,
    )


class TestTheSmallPath:
    """If the attachment size is less than `MAX_ATTACHMENT_BYTES`, only one Graph call happens:
    the inline `POST .../attachments` request. This test class never registers a route for
    `createUploadSession`. If the code calls `createUploadSession`, respx raises its own
    unmatched-request error instead. No assertion in this file names that error directly.
    """

    async def test_a_small_file_attaches_inline_with_no_upload_session(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        inline = _inline_route(graph)

        await _upload(client, transport, content=_bytes(MAX_ATTACHMENT_BYTES - 1))

        assert inline.called
        sent = inline.calls.last.request
        assert sent.headers["content-type"] == "application/json"

    async def test_a_small_file_reaches_a_shared_mailbox_by_the_same_split_graph_mailbox_uses(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        inline = _inline_route(graph, base=_SHARED_MESSAGES)

        await _upload(
            client,
            transport,
            content=_bytes(MAX_ATTACHMENT_BYTES - 1),
            mailbox="shared@example.invalid",
        )

        assert inline.called


class TestTheUploadSessionPath:
    """If the attachment size is `MAX_ATTACHMENT_BYTES` or more, `createUploadSession` runs
    first. Then the file goes to `uploadUrl` in `PUT` requests of `UPLOAD_CHUNK_BYTES` each.
    Every `PUT` is full size, except the last one. The last `PUT` carries only the remaining
    bytes.
    """

    async def test_a_large_file_is_split_into_correctly_sized_chunks(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        total = UPLOAD_CHUNK_BYTES + 1_000
        content = _bytes(total)
        _session_route(graph)
        chunks = graph.route(method="PUT", host="attachment-upload.invalid").mock(
            return_value=httpx.Response(200)
        )

        await _upload(client, transport, content=content)

        assert chunks.call_count == 2
        first, second = (call.request for call in cast("Sequence[Call]", chunks.calls))
        assert first.headers["Content-Length"] == str(UPLOAD_CHUNK_BYTES)
        assert first.headers["Content-Range"] == f"bytes 0-{UPLOAD_CHUNK_BYTES - 1}/{total}"
        assert first.content == content[:UPLOAD_CHUNK_BYTES]
        assert second.headers["Content-Length"] == "1000"
        assert second.headers["Content-Range"] == f"bytes {UPLOAD_CHUNK_BYTES}-{total - 1}/{total}"
        assert second.content == content[UPLOAD_CHUNK_BYTES:]
        assert first.headers["Content-Type"] == "application/octet-stream"
        assert second.headers["Content-Type"] == "application/octet-stream"

    async def test_a_308_response_is_treated_as_continue_not_failure(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        total = UPLOAD_CHUNK_BYTES + 1_000
        _session_route(graph)
        chunks = graph.route(method="PUT", host="attachment-upload.invalid").mock(
            side_effect=[httpx.Response(308), httpx.Response(201)]
        )

        await _upload(client, transport, content=_bytes(total))

        assert chunks.call_count == 2

    async def test_a_failed_chunk_raises_and_stops_uploading(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        total = UPLOAD_CHUNK_BYTES + 1_000
        _session_route(graph)
        chunks = graph.route(method="PUT", host="attachment-upload.invalid").mock(
            return_value=httpx.Response(500, text="synthetic upload-session failure")
        )

        with pytest.raises(GraphFailure):
            await _upload(client, transport, content=_bytes(total))

        assert chunks.call_count == 1
