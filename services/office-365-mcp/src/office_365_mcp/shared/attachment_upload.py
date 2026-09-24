"""This module attaches one file, of any size, to a message that Graph already created.

Under 3 MB, Graph accepts a `fileAttachment` in one `POST .../attachments` call. At 3 MB or
more, the file goes through an upload session instead. Graph calls `createUploadSession`, then
sends a series of `PUT` calls to the URL it returns.

`upload_attachment` is the one function that both `outlook_draft_mail` and `outlook_draft_reply`
call to attach a file. The file size alone decides which Graph calls happen.
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

# The byte range of each PUT must be a multiple of 320 KiB. Graph recommends less than 4 MiB
# for each request.
UPLOAD_CHUNK_BYTES = 12 * 320 * 1024

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_OCTET_STREAM = "application/octet-stream"

# TRAP: the upload-session host can answer an intermediate PUT with 308 Resume Incomplete.
# Microsoft's own walkthrough does not mention this response.
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
    """Attach `content` to the message that `message_id` names. The function picks the inline
    path or the upload-session path by size alone.

    The function raises `GraphFailure` on any refusal, and does not catch it. The caller must
    decide whether a partial success is worth a report.

    `mailbox` and `message_id` resolve through `shared.seam.graph_mailbox`. `message_id` must
    already be in the immutable id space that this call requests.

    The function asserts that `len(content) <= MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION`, instead
    of raising an error that the caller can catch. A file above this size at this point is a
    programming error in the caller, not a bad request for Graph to explain.
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
    """This is the path for a file under 3 MB. It uses one `POST .../attachments` call, in
    Graph's own small-attachment shape."""
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
    """This is the path for a file of 3 MB or more. It makes one `createUploadSession` call
    through the SDK. Then it sends the file in ordered chunks through raw `httpx`, until the
    last chunk lands."""
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
    """This function yields every `(start, end)` pair that a chunked upload sends in a PUT call,
    in ascending order. `end` is exclusive."""
    for start in range(0, total, UPLOAD_CHUNK_BYTES):
        yield start, min(start + UPLOAD_CHUNK_BYTES, total)


def _immutable_ids() -> HeadersCollection:
    """This function builds a new collection for each call. A shared default collection would
    leak into every other Graph call."""
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return headers
