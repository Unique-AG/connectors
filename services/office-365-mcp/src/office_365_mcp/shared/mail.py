import re
from typing import Literal, Self

from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.message import Message
from msgraph.generated.models.recipient import Recipient
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import MailMessageHandle

SUMMARY_FIELDS: tuple[str, ...] = (
    "id",
    "subject",
    "bodyPreview",
    "from",
    "toRecipients",
    "receivedDateTime",
    "isRead",
    "hasAttachments",
    "parentFolderId",
    "webLink",
)

PREVIEW_CHARACTERS = 255

ONE_ADDRESS = re.compile(r"\A[^\s<>,;:\"@]+@[^\s<>,;:\"@]+\Z")


type WellKnownFolder = Literal[
    "inbox",
    "sentitems",
    "drafts",
    "archive",
    "deleteditems",
    "junkemail",
    "clutter",
]


class MailAddress(BaseModel):
    name: str | None = Field(description="The display name on the message, or null if none.")
    address: str | None = Field(description="The SMTP address, or null if none.")

    @classmethod
    def from_recipient(cls, recipient: Recipient | None) -> Self | None:
        if recipient is None or recipient.email_address is None:
            return None
        return cls(name=recipient.email_address.name, address=recipient.email_address.address)

    @classmethod
    def from_email_address(cls, address: EmailAddress | None) -> Self | None:
        if address is None:
            return None
        return cls(name=address.name, address=address.address)

    @classmethod
    def each_of(cls, recipients: list[Recipient] | None) -> list[Self]:
        return [
            address
            for address in (cls.from_recipient(recipient) for recipient in recipients or [])
            if address is not None
        ]


class MailSummary(BaseModel):
    uri: str = Field(
        description="A handle for this message; pass it to outlook_read_mail to read the body."
    )
    subject: str | None = Field(description="The subject line, or null if none was set.")
    preview: str | None = Field(
        description=f"The first {PREVIEW_CHARACTERS} characters of the body as plain text."
    )
    sender: MailAddress | None = Field(description="Who sent the message, or null if none.")
    to: list[MailAddress] = Field(description="The To recipients.")
    received_at: str | None = Field(
        description="When the mailbox received the message, in ISO-8601 UTC, or null for a draft."
    )
    is_read: bool | None = Field(description="Whether the message is marked read.")
    has_attachments: bool | None = Field(description="Whether Graph reports attachments.")
    folder_id: str | None = Field(description="The Graph id of the folder holding the message.")
    web_link: str | None = Field(description="A link that opens the message in Outlook on the web.")

    @classmethod
    def from_message(cls, message: Message, *, message_id: str) -> Self:
        return cls(
            uri=MailMessageHandle(message_id).uri,
            subject=message.subject,
            preview=message.body_preview,
            sender=MailAddress.from_recipient(message.from_),
            to=MailAddress.each_of(message.to_recipients),
            received_at=(
                None
                if message.received_date_time is None
                else message.received_date_time.isoformat()
            ),
            is_read=message.is_read,
            has_attachments=message.has_attachments,
            folder_id=message.parent_folder_id,
            web_link=message.web_link,
        )
