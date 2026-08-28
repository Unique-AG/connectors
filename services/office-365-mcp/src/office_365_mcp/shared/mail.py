"""What an Outlook message is: the shape every reader answers in, and the fields they all ask for.

Four tools find or list mail and one reads it. They agree here rather than each deciding, because
the difference a caller would see is not cosmetic: a summary that carried a preview from one tool
and none from another reads as "this message has no text", and an address normalised two ways
compares unequal to itself.

`SUMMARY_FIELDS` is `$select` for all of them. Asking for the same set is what makes a hit from a
search and a row from a folder listing the same thing — and `$select` is not an optimisation here:
Microsoft warns that a large page without one risks a gateway timeout, and `body` on twenty-five
messages is tens of thousands of tokens nobody asked for.
"""

from typing import Self

from msgraph.generated.models.message import Message
from msgraph.generated.models.recipient import Recipient
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import MailMessageHandle

# Every property a summary reads, and nothing else. `bodyPreview` is the one field here that
# `Mail.ReadBasic` withholds, which is why the reading tools declare `Mail.Read`: a hit list with
# no snippet is a list of subjects a model cannot triage.
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

# Microsoft's own documented length for `bodyPreview`, named here because two tools quote it to a
# model and a number that drifted in one of them would be a promise the other did not make.
PREVIEW_CHARACTERS = 255


class MailAddress(BaseModel):
    """One person or mailbox on a message, as Graph's `emailAddress` gives it."""

    name: str | None = Field(
        description=(
            "The display name on the message. Written by whoever sent it, so on inbound mail it "
            + "is text a stranger chose and matches nobody's directory entry by necessity. "
            + "Null when Graph recorded none."
        )
    )
    address: str | None = Field(
        description=(
            "The SMTP address. This is the value to compare, to quote back and to reuse. Null "
            + "only for a message Graph recorded no address for, which happens on some drafts."
        )
    )

    @classmethod
    def from_recipient(cls, recipient: Recipient | None) -> Self | None:
        """The address, or None when Graph named nobody — a draft with an empty `to`, or a message
        whose sender it did not record."""
        if recipient is None or recipient.email_address is None:
            return None
        return cls(name=recipient.email_address.name, address=recipient.email_address.address)

    @classmethod
    def each_of(cls, recipients: list[Recipient] | None) -> list[Self]:
        return [
            address
            for address in (cls.from_recipient(recipient) for recipient in recipients or [])
            if address is not None
        ]


class MailSummary(BaseModel):
    """One message as every finder and lister answers it: enough to choose, never the whole body."""

    uri: str = Field(
        description=(
            "A handle for this exact message, `outlook:///messages/{id}` with the id "
            + "percent-encoded. Pass it verbatim to outlook_read_mail for the body. It stays "
            + "valid when the message is filed into another folder, which Outlook does on its own "
            + "through inbox rules and retention."
        )
    )
    subject: str | None = Field(
        description="The subject line. Null when the message was sent without one."
    )
    preview: str | None = Field(
        description=(
            f"The first {PREVIEW_CHARACTERS} characters of the body, as plain text, from the very "
            + "top. On a reply that is usually the quoted header block rather than what the "
            + "sender wrote, so a preview that does not answer the question is not evidence the "
            + "message does not: read the message before concluding. Null under a permission that "
            + "withholds it."
        )
    )
    sender: MailAddress | None = Field(
        description="Who sent it. Null for a message Graph recorded no sender for."
    )
    to: list[MailAddress] = Field(
        description=(
            "The To recipients, and only those. Cc and Bcc are not read here — outlook_read_mail "
            + "reports Cc. An empty list means Graph returned none, not that nobody was addressed."
        )
    )
    received_at: str | None = Field(
        description=(
            "When the mailbox received it, ISO-8601 in UTC. Null on a draft, which was never "
            + "received. Compare and sort on this rather than on anything in the subject."
        )
    )
    is_read: bool | None = Field(
        description="Whether the message is marked read. Null when Graph did not say."
    )
    has_attachments: bool | None = Field(
        description=(
            "Whether Graph reports attachments. No tool here returns attachment bytes or names. "
            + "Note this is false for a message whose only attachment is an inline image."
        )
    )
    folder_id: str | None = Field(
        description=(
            "The Graph id of the folder holding the message. Opaque, and no tool here turns it "
            + "into a folder name — outlook_browse_folders reports id and name together."
        )
    )
    web_link: str | None = Field(
        description=(
            "Graph's own link that opens the message in Outlook on the web, passed through "
            + "exactly as Graph gave it. Never assembled here, and never repaired: Microsoft "
            + "changed the format in 2025 and a hand-built link opens the wrong item or none."
        )
    )

    @classmethod
    def from_message(cls, message: Message, *, message_id: str) -> Self:
        """`message_id` is passed in rather than read off `message`, because a hit found by
        `$search` carries a mutable id that the caller has already exchanged for a stable one."""
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
