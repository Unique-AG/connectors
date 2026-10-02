from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Self

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.attachment import Attachment
from msgraph.generated.models.attachment_collection_response import AttachmentCollectionResponse
from msgraph.generated.models.file_attachment import FileAttachment
from msgraph.generated.models.item_attachment import ItemAttachment
from msgraph.generated.models.reference_attachment import ReferenceAttachment
from msgraph.generated.users.item.messages.item.attachments.attachments_request_builder import (
    AttachmentsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    MAX_SCANNED_ITEMS,
    CollectedItems,
    collect_pages,
    graph_step,
)
from office_365_mcp.shared.handles import MailAttachmentHandle, MailMessageHandle
from office_365_mcp.shared.immutable_ids import immutable_id_headers
from office_365_mcp.shared.seam import FileFromGraph, graph_mailbox

STEP_MESSAGE_ATTACHMENTS = "message_attachments"

MAX_BYTES = 10 * 1024 * 1024

MEGABYTE = 1024 * 1024

_DEFAULT_MEDIA_TYPE = "application/octet-stream"

_AttachmentsQuery = AttachmentsRequestBuilder.AttachmentsRequestBuilderGetQueryParameters

ATTACHMENT_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "contentType",
    "size",
    "isInline",
    "lastModifiedDateTime",
)

type AttachmentKind = Literal["file", "item", "reference", "unknown"]


class AttachmentSummary(BaseModel):
    uri: str = Field(
        description=(
            "The handle of this attachment. It names the message or the event that holds the "
            "attachment, and then the attachment itself. Copy the handle word for word. Do not "
            "build a handle from a name or an id."
        )
    )
    name: str | None = Field(
        description=(
            "The name of the attachment, for example the file name `Invoice.pdf`. Two "
            "attachments can have the same name, so use the `uri` to tell them apart. The value "
            "is null if Microsoft 365 reports none."
        )
    )
    content_type: str | None = Field(
        description=(
            "The MIME type of the attachment, as Microsoft 365 reports it, for example "
            "`application/pdf`. The value is null if Microsoft 365 reports none."
        )
    )
    size: int | None = Field(
        description=(
            "The size of the attachment in bytes, as Microsoft 365 reports it. The tool that "
            "reads attachments refuses a file that is too large, so look at this value first. "
            "The value is null if Microsoft 365 reports none."
        )
    )
    is_inline: bool | None = Field(
        description=(
            "True if the attachment shows inside the body of the message or the event, for "
            "example an image in a signature. False if it is a separate attachment. The value is "
            "null if Microsoft 365 reports none."
        )
    )
    kind: AttachmentKind = Field(
        description=(
            "The type of the attachment. `file` is a file. `item` is an attached Outlook item, "
            "for example a message, an event, or a contact. `reference` is a link to a file in "
            "cloud storage. `unknown` is a type that this connector does not recognize."
        )
    )
    last_modified_at: str | None = Field(
        description=(
            "The time of the last change to the attachment, in ISO-8601 UTC, for example "
            "`2026-04-02T03:41:29+00:00`. The value is null if Microsoft 365 reports none."
        )
    )

    @classmethod
    def from_attachment(cls, attachment: Attachment, *, uri: str) -> Self:
        return cls(
            uri=uri,
            name=attachment.name,
            content_type=attachment.content_type,
            size=attachment.size,
            is_inline=attachment.is_inline,
            kind=_kind(attachment),
            last_modified_at=(
                None
                if attachment.last_modified_date_time is None
                else attachment.last_modified_date_time.isoformat()
            ),
        )


def _kind(attachment: Attachment) -> AttachmentKind:
    if isinstance(attachment, FileAttachment):
        return "file"
    if isinstance(attachment, ItemAttachment):
        return "item"
    if isinstance(attachment, ReferenceAttachment):
        return "reference"
    return "unknown"


@dataclass(frozen=True, slots=True)
class AttachmentRefusals:
    an_item: str
    a_link: str
    no_size: str
    nothing_came_back: str
    too_large: Callable[[int], str]


async def message_attachments(
    client: GraphServiceClient, *, handle: MailMessageHandle, mailbox: str | None = None
) -> CollectedItems[AttachmentSummary]:
    with graph_step(STEP_MESSAGE_ATTACHMENTS):
        first_page = await (
            graph_mailbox(client, mailbox)
            .messages.by_message_id(handle.message_id)
            .attachments.get(
                request_configuration=RequestConfiguration[_AttachmentsQuery](
                    query_parameters=_AttachmentsQuery(select=list(ATTACHMENT_FIELDS)),
                    headers=immutable_id_headers(),
                )
            )
        )
        return await collect_attachments(
            first_page,
            client,
            uri_of=lambda attachment_id: MailAttachmentHandle(handle.message_id, attachment_id).uri,
        )


async def collect_attachments(
    first_page: AttachmentCollectionResponse | None,
    client: GraphServiceClient,
    *,
    uri_of: Callable[[str], str],
) -> CollectedItems[AttachmentSummary]:
    assert first_page is not None, "Graph answered an attachment listing with no collection"
    collected = await collect_pages(
        first_page, client, limit=MAX_SCANNED_ITEMS, headers=immutable_id_headers()
    )
    return CollectedItems(
        items=[_row(attachment, uri_of) for attachment in collected.items],
        capped=collected.capped,
    )


def _row(attachment: Attachment, uri_of: Callable[[str], str]) -> AttachmentSummary:
    assert attachment.id is not None, "Graph answered an attachment with no id"
    return AttachmentSummary.from_attachment(attachment, uri=uri_of(attachment.id))


def refusal_before_download(summary: AttachmentSummary, refusals: AttachmentRefusals) -> str | None:
    if summary.kind == "item":
        return refusals.an_item
    if summary.kind == "reference":
        return refusals.a_link
    if summary.size is None:
        return refusals.no_size
    if summary.size > MAX_BYTES:
        return refusals.too_large(summary.size)
    return None


async def fetch_file_or_refusal(
    describe: Callable[[], Awaitable[Attachment | None]],
    download: Callable[[], Awaitable[Attachment | None]],
    *,
    uri: str,
    refusals: AttachmentRefusals,
) -> FileFromGraph | str:
    described = await describe()
    assert described is not None, "Graph answered an attachment read with no attachment"
    summary = AttachmentSummary.from_attachment(described, uri=uri)
    refused = refusal_before_download(summary, refusals)
    if refused is not None:
        return refused
    return file_or_refusal(summary, await download(), refusals)


def file_or_refusal(
    summary: AttachmentSummary, downloaded: Attachment | None, refusals: AttachmentRefusals
) -> FileFromGraph | str:
    assert summary.size is not None, "the size refusal comes before any download"
    content = downloaded.content_bytes if isinstance(downloaded, FileAttachment) else None
    if not content and summary.size > 0:
        return refusals.nothing_came_back
    body = content or b""
    if len(body) > MAX_BYTES:
        return refusals.too_large(len(body))
    return FileFromGraph(body, name=summary.name, mime_type=media_type(summary.content_type, body))


def media_type(content_type: str | None, body: bytes) -> str:
    if content_type is None:
        return _DEFAULT_MEDIA_TYPE
    reported = content_type.split(";", 1)[0].strip().lower()
    top, _, sub = reported.partition("/")
    if not top or not sub:
        return _DEFAULT_MEDIA_TYPE
    if top == "text" and not _is_utf8(body):
        return _DEFAULT_MEDIA_TYPE
    return reported


def _is_utf8(body: bytes) -> bool:
    try:
        _ = body.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
