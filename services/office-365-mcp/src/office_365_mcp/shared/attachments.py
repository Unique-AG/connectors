from typing import Literal, Self

from msgraph.generated.models.attachment import Attachment
from msgraph.generated.models.file_attachment import FileAttachment
from msgraph.generated.models.item_attachment import ItemAttachment
from msgraph.generated.models.reference_attachment import ReferenceAttachment
from pydantic import BaseModel, Field

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
