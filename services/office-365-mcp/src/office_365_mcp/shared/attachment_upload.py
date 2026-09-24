"""Attaching one file, of any size, to a message Graph already created — the mechanic Graph
splits in two by size, and the reason this module exists apart from `shared/mail.py`.

Under 3 MB, Graph accepts a `fileAttachment` in a single `POST .../attachments` call, and refuses
that same call at or above it: Microsoft's own error for the boundary is
`ErrorAttachmentSizeShouldNotBeLessThanMinimumSize`, raised from the OTHER route — the one below —
because that is the route a 3 MB-and-up file is supposed to take instead
(https://learn.microsoft.com/en-us/graph/outlook-large-attachments). That route is an upload
session: `createUploadSession`, then a sequence of `PUT`s to the opaque URL it returns, each
carrying one byte range of the file, until the last one lands. `upload_attachment` is the one
function both `outlook_draft_mail` and `outlook_draft_reply` call to attach a file either way —
the size alone decides which Graph calls happen, and neither tool has to know which.

Ported from `services/outlook-semantic-mcp`'s
`email-attachments/upload-in-memory-attachment.command.ts` and its sibling `utils.ts`, the
TypeScript connector that solved this exact problem against this exact Graph API first. The
mechanics carry over: the same 3 MB split, the same 12 × 320 KiB chunk size, the same
`application/octet-stream` forced onto every chunk regardless of the file's real MIME type, the
same tolerance for a 308 mid-upload. What does not carry over is the shape: that file drives
`undici`'s `fetch` by hand inside a NestJS command; this one drives `httpx` inside a plain async
function, and the generated SDK's own `createUploadSession` request builder replaces a hand-built
URL and header set for that one call.
"""

from collections.abc import Iterator
from typing import cast

import httpx
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.attachment_item import AttachmentItem
from msgraph.generated.models.attachment_type import AttachmentType
from msgraph.generated.models.file_attachment import FileAttachment
from msgraph.generated.users.item.messages.item.attachments.attachments_request_builder import (
    AttachmentsRequestBuilder,
)
from msgraph.generated.users.item.messages.item.attachments.create_upload_session.create_upload_session_post_request_body import (  # noqa: E501
    CreateUploadSessionPostRequestBody,
)
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphFailure, graph_step, no_retry
from office_365_mcp.shared.mail import MAX_ATTACHMENT_BYTES, MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION
from office_365_mcp.shared.seam import graph_mailbox

STEP_ATTACH_INLINE = "attach_inline"
STEP_CREATE_UPLOAD_SESSION = "create_upload_session"
STEP_UPLOAD_SESSION_CHUNKS = "upload_session_chunks"

# Graph requires each PUT's byte range to be a multiple of 320 KiB and recommends staying under
# 4 MiB per request "for better performance"
# (https://learn.microsoft.com/en-us/graph/outlook-large-attachments). 12 × 320 KiB = 3,932,160
# bytes (~3.75 MB): the largest multiple of 320 KiB under that recommended ceiling, and the same
# figure `email-attachments/utils.ts` in `outlook-semantic-mcp` already uses against this same
# upload-session endpoint.
UPLOAD_CHUNK_BYTES = 12 * 320 * 1024

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_OCTET_STREAM = "application/octet-stream"

# Microsoft's own walkthrough documents 200 OK for an intermediate PUT and 201 Created for the
# final one — both already `is_success` — and never mentions 308
# (https://learn.microsoft.com/en-us/graph/outlook-large-attachments, "Step 3"). TRAP: the
# upload-session host has been observed answering an intermediate PUT with 308 Resume Incomplete
# instead, the convention plain HTTP resumable uploads use elsewhere; `email-attachments/
# upload-in-memory-attachment.command.ts` in `outlook-semantic-mcp` guards for exactly this
# alongside its own `response.ok`, and this module keeps that same tolerance rather than trusting
# the two documented status codes alone.
_RESUME_INCOMPLETE = 308


async def upload_attachment(
    client: GraphServiceClient,
    transport: httpx.AsyncClient,
    *,
    mailbox: str | None,
    message_id: str,
    name: str,
    content_type: str,
    content: bytes,
) -> None:
    """Attach `content` to the message `message_id` already names, choosing the inline path or
    the upload-session path by size alone. Raises `GraphFailure` on any refusal and never catches
    one itself, so a caller that wants to report a partial success (`outlook_draft_reply`, which
    keeps whatever attached before the first refusal) or let the failure end the call
    (`outlook_draft_mail`) decides that for itself; this function only ever does the whole thing
    or raises out of however far it got.

    `client` reaches Graph's own routes for both paths: `POST .../attachments` for the small one,
    `POST .../attachments/createUploadSession` for the large one's first call. `transport` is the
    same shared `httpx.AsyncClient` `client` was itself built from
    (`office_365_mcp.graph_client.graph_client_for`), reused rather than opened a second time, for
    the large path's chunk `PUT`s alone: the `uploadUrl` `createUploadSession` returns is a
    pre-authenticated, Microsoft-hosted URL outside `graph.microsoft.com`
    (`https://outlook.office.com/api/...?authtoken=...`), not a Graph route the generated SDK has
    any request builder for, so those `PUT`s go straight through `transport` instead of `client`.

    `mailbox` and `message_id` mirror `shared.seam.graph_mailbox`'s own two inputs exactly,
    because that is what resolves them: `None` for the signed-in user's own mailbox, otherwise the
    shared or delegated one Exchange grants the signed-in user access to. `message_id` must
    already be in the immutable id space this call requests with `Prefer: IdType="ImmutableId"` —
    the same space `outlook_draft_mail` and `outlook_draft_reply` create their draft in, and the
    one thing every Graph call in this function shares with the rest of this connector's mail
    tools.

    Both Graph calls this function can make are declared under the same `Mail.ReadWrite` /
    `Mail.ReadWrite.Shared` permissions `outlook_draft_mail` and `outlook_draft_reply` already
    request: Microsoft documents `Mail.ReadWrite` as what `createUploadSession` needs for a
    message (as opposed to an event, which needs `Calendars.ReadWrite` instead) — see the
    "Permissions" section of the URL above — and the chunk `PUT`s carry no bearer token of this
    connector's own to scope at all, only the pre-authenticated `uploadUrl`. No new consent is
    needed for this function to work.

    Neither Graph call here is retried. `no_retry()` covers `createUploadSession`, for the same
    reason `outlook_draft_mail` and `outlook_draft_reply` put it on every write of their own:
    Microsoft publishes no idempotency key for it, so a retried POST after a 503 that already
    succeeded opens a second, orphaned upload session. The chunk `PUT`s need no equivalent: they
    never reach `client`'s request adapter at all, so kiota's retry middleware — the thing
    `no_retry()` turns off — was never in their path to begin with, and `transport` itself retries
    nothing on its own. A failed chunk simply raises, out of whichever chunk failed.

    Asserts `len(content) <= MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION` rather than raising a catch-
    able error: a caller-facing refusal belongs at the tool boundary, worded for whichever tool is
    calling this and ideally raised before `content` is even decoded from base64. Reaching this
    function with an oversized file is a programming error in the caller, not a bad request for
    Graph to explain.
    """
    assert len(content) <= MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION, (
        f"attachment size is bounded at the tool boundary, got {len(content)} bytes"
    )
    attachments = graph_mailbox(client, mailbox).messages.by_message_id(message_id).attachments
    if len(content) < MAX_ATTACHMENT_BYTES:
        await _attach_inline(attachments, name=name, content_type=content_type, content=content)
        return
    await _attach_via_upload_session(
        attachments, transport, name=name, content_type=content_type, content=content
    )


async def _attach_inline(
    attachments: AttachmentsRequestBuilder, *, name: str, content_type: str, content: bytes
) -> None:
    """The under-3-MB path: one `POST .../attachments` call, Graph's own small-attachment shape —
    the same call `outlook_draft_reply._attach` already makes per file today."""
    with graph_step(STEP_ATTACH_INLINE):
        await attachments.post(
            FileAttachment(name=name, content_type=content_type, content_bytes=content),
            request_configuration=RequestConfiguration[QueryParameters](
                options=no_retry(), headers=_immutable_ids()
            ),
        )


async def _attach_via_upload_session(
    attachments: AttachmentsRequestBuilder,
    transport: httpx.AsyncClient,
    *,
    name: str,
    content_type: str,
    content: bytes,
) -> None:
    """The 3 MB-and-up path: one `createUploadSession` call through the SDK, then the file in
    ordered chunks through raw `httpx`, until the last one lands."""
    total = len(content)
    with graph_step(STEP_CREATE_UPLOAD_SESSION):
        session = await attachments.create_upload_session.post(
            CreateUploadSessionPostRequestBody(
                attachment_item=AttachmentItem(
                    attachment_type=AttachmentType.File,
                    name=name,
                    size=total,
                    content_type=content_type,
                )
            ),
            request_configuration=RequestConfiguration[QueryParameters](
                options=no_retry(), headers=_immutable_ids()
            ),
        )
    assert session is not None, "Graph answered createUploadSession with no session"
    assert session.upload_url is not None, "Graph answered createUploadSession with no uploadUrl"
    upload_url = session.upload_url

    with graph_step(STEP_UPLOAD_SESSION_CHUNKS):
        for start, end in _chunk_ranges(total):
            response = await transport.put(
                upload_url,
                content=content[start:end],
                headers={
                    "Content-Length": str(end - start),
                    "Content-Range": f"bytes {start}-{end - 1}/{total}",
                    "Content-Type": _OCTET_STREAM,
                },
            )
            if not (response.is_success or response.status_code == _RESUME_INCOMPLETE):
                raise GraphFailure(
                    f"Microsoft Graph rejected an attachment-upload chunk for {name!r} "
                    + f"({response.status_code})",
                    status=response.status_code,
                    code=None,
                    request_id=cast("str | None", response.headers.get("request-id")),
                )


def _chunk_ranges(total: int) -> Iterator[tuple[int, int]]:
    """Every `(start, end)` pair a chunked upload PUTs, `end` exclusive, in ascending, contiguous
    order. The last pair is short exactly when `total` is not a multiple of `UPLOAD_CHUNK_BYTES`;
    Graph reads each PUT's own `Content-Range`, so a short final chunk needs no padding to fit."""
    for start in range(0, total, UPLOAD_CHUNK_BYTES):
        yield start, min(start + UPLOAD_CHUNK_BYTES, total)


def _immutable_ids() -> HeadersCollection:
    """Built per call: kiota's `RequestConfiguration.headers` default is one collection shared by
    every configuration in the process, so a preference added to it leaks onto every Graph call —
    the same trap `outlook_draft_mail`'s and `outlook_draft_reply`'s own copies of this guard
    against."""
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return headers
