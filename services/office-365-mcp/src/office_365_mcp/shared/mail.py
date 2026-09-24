"""What an Outlook message is: the shape every reader answers in, and the fields they all ask for.

Four tools find or list mail, and one tool reads it. They agree here on one shape. No tool
decides this on its own, because the difference a caller sees is not cosmetic: a summary that
carries a preview from one tool and none from another reads as "this message has no text", and an
address normalized two ways compares unequal to itself.

`SUMMARY_FIELDS` is the `$select` list for all of them. The same set makes a hit from search and a
row from a folder listing into the same shape.

`$select` is not just an optimization here. Microsoft warns that a large page with no `$select`
risks a gateway timeout. `body` alone on twenty-five messages is tens of thousands of tokens that
nobody asked for.
"""

import base64
import re
from typing import Literal, Self

from msgraph.generated.models.email_address import EmailAddress
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
# model. If the number drifts in just one tool, that tool promises something the other does not.
PREVIEW_CHARACTERS = 255

# One SMTP address, no display name and no list: Exchange either rejects `Ada <ada@x.invalid>` or
# silently reads the whole string as a name.
ONE_ADDRESS = re.compile(r"\A[^\s<>,;:\"@]+@[^\s<>,;:\"@]+\Z")

# Shared by outlook_draft_mail and outlook_draft_reply, the only two tools that attach a file.
# `outlook_send_draft` needs neither: it cannot touch an attachment at all, by the same absent-
# argument control it applies to everything else about the message.
MAX_ATTACHMENTS = 10

# Microsoft's own ceiling for a `fileAttachment` added through a single `POST .../attachments`
# call, the cheapest of the two ways this connector attaches a file: "This operation limits the
# size of the attachment you can add to under 3 MB"
# (https://learn.microsoft.com/en-us/graph/outlook-large-attachments). Measured against the
# DECODED bytes, which is what that ceiling counts; a caller's base64 text runs a third longer. A
# file at or over this line still attaches — see `MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION` — just
# not through this single call.
MAX_ATTACHMENT_BYTES = 3 * 1024 * 1024

# Microsoft's own ceiling for a single attachment on a message at all, inline or not: "you can
# attach files up to 150 MB to an Outlook message or event item"
# (https://learn.microsoft.com/en-us/graph/outlook-large-attachments). A file from
# `MAX_ATTACHMENT_BYTES` up to this line attaches through an upload session instead of the single
# inline call — `shared.attachment_upload.upload_attachment` is what carries either path out, and
# the split is invisible above that function. Measured against the same DECODED bytes as
# `MAX_ATTACHMENT_BYTES`.
MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION = 150 * 1024 * 1024

# Reused verbatim by both attaching tools, for the reason `MAILBOX_FIELD` in `shared/seam.py` is:
# one text every caller agrees with, not one chance per tool to drift from the other.
ATTACHMENTS_FIELD: str = (
    f"Files to attach, at most {MAX_ATTACHMENTS}. Each entry is Graph's own small-attachment "
    + "shape: `name` (the file name shown to the recipient), `content_type` (a MIME type, for "
    + "example `application/pdf`), and `content_bytes` (the file's own bytes, base64-encoded — "
    + "`contentBytes` on the wire). Every entry's DECODED size must be under "
    + f"{MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION // (1024 * 1024)} MB, Microsoft's own ceiling for "
    + "a single attachment on an Outlook item "
    + "(https://learn.microsoft.com/en-us/graph/outlook-large-attachments). A file under "
    + f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB attaches directly; a larger one attaches "
    + "through Microsoft's own upload session instead, which this connector carries out for you — "
    + "this argument takes the same shape either way. Omit this, or pass an empty list, for a "
    + "draft with no attachment."
)


# The well-known folder names Graph accepts in a URL path are the seven of seventeen that a
# person says out loud. They are locale-independent, so `inbox` reaches the Inbox of a mailbox in
# any language.
#
# The other ten are left out on purpose. `conflicts`, `localfailures`, `serverfailures` and
# `syncissues` are Outlook's own sync diagnostics, not mail. `msgfolderroot` and `searchfolders`
# are parents, not message folders. `recoverableitemsdeletions` is the purge bin, and Microsoft
# says it "isn't visible in any Outlook email client". `outbox` holds a message for the seconds
# before it leaves, so listing it is a race. `conversationhistory` is Skype and Teams history.
# `scheduled` exists for Outlook on iOS alone.
#
# A folder outside this list is reached by its handle from outlook_browse_folders, never by name.
# A custom folder's name belongs to the user, and matching one by string is how a tool files mail
# into the wrong place.
type WellKnownFolder = Literal[
    "inbox",
    "sentitems",
    "drafts",
    "archive",
    "deleteditems",
    "junkemail",
    "clutter",
]


class MailAttachmentInput(BaseModel):
    """One small file a caller wants attached, exactly as the schema takes it: Graph's own
    `fileAttachment` shape, minus the parts Graph fills in itself (`id`, `size`, `isInline`)."""

    name: str = Field(min_length=1, description="The file name, shown to the recipient verbatim.")
    content_type: str = Field(
        min_length=1, description="The file's MIME type, for example `application/pdf`."
    )
    content_bytes: str = Field(
        min_length=1,
        description="The file's own bytes, base64-encoded — Graph's own `contentBytes` shape.",
    )


class MailAttachmentSummary(BaseModel):
    """One attachment as a tool left it. Name, MIME type and decoded size are inert data Graph
    stores verbatim rather than something it decides, unlike a recipient Graph can resolve or drop
    — so there is no discrepancy here for a read-back to catch, and a caller can trust this."""

    name: str = Field(description="The file name, exactly as given.")
    content_type: str = Field(description="The MIME type, exactly as given.")
    size: int = Field(description="The attachment's decoded size, in bytes.")


def decode_attachment(content_bytes: str) -> bytes | None:
    """`content_bytes` as the raw bytes Graph's `fileAttachment.contentBytes` wants, or `None`
    when it is not valid base64.

    `validate=True` refuses a string with non-alphabet characters rather than silently discarding
    them, which is what plain `base64.b64decode` does: a caller's corrupted or truncated base64
    would otherwise decode into fewer, wrong bytes instead of failing here, at the one point that
    can still refuse before anything reaches Graph.
    """
    try:
        return base64.b64decode(content_bytes, validate=True)
    except ValueError:
        # `binascii.Error` is a `ValueError` subclass, which is what `validate=True` raises for
        # non-alphabet characters; a bare string with no valid characters at all raises the plain
        # base `ValueError` instead, so both are caught here rather than the narrower type alone.
        return None


class MailAddress(BaseModel):
    """One person or mailbox on a message, as Graph's `emailAddress` gives it."""

    name: str | None = Field(
        description=(
            "The display name on the message. Whoever sent the message wrote it, so on inbound "
            + "mail it is text a stranger chose, and it never matches anybody's directory entry. "
            + "Null when Graph recorded none."
        )
    )
    address: str | None = Field(
        description=(
            "The SMTP address. This address is the value to compare, to quote, and to reuse. "
            + "Null only for a message that Graph recorded no address for, which happens on "
            + "some drafts."
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
    def from_email_address(cls, address: EmailAddress | None) -> Self | None:
        """Graph does not wrap a calendar's `owner` in a `recipient`; it is a bare `emailAddress`
        (https://learn.microsoft.com/en-us/graph/api/resources/calendar)."""
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
            + "top. On a reply, this is usually the quoted header block rather than what the "
            + "sender wrote. If the preview does not answer the question, that is not evidence "
            + "that the message does not either. Read the message first. Null under a permission "
            + "that withholds it."
        )
    )
    sender: MailAddress | None = Field(
        description="Who sent it. Null for a message that Graph recorded no sender for."
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
            + "received. Compare and sort on this timestamp rather than on anything in the "
            + "subject."
        )
    )
    is_read: bool | None = Field(
        description="Whether the message is marked read. Null when Graph did not say."
    )
    has_attachments: bool | None = Field(
        description=(
            "Whether Graph reports attachments. No tool here returns attachment bytes or names. "
            + "This value is false for a message whose only attachment is an inline image."
        )
    )
    folder_id: str | None = Field(
        description=(
            "The Graph id of the folder holding the message. This id is opaque, and no tool here "
            + "turns it into a folder name. outlook_browse_folders reports the id and the name "
            + "together."
        )
    )
    web_link: str | None = Field(
        description=(
            "Graph's own link that opens the message in Outlook on the web, passed through "
            + "exactly as Graph gave it. This connector never assembles or repairs it. Microsoft "
            + "changed the format in 2025, so a hand-built link opens the wrong item or none."
        )
    )

    @classmethod
    def from_message(cls, message: Message, *, message_id: str) -> Self:
        """`message_id` is passed in rather than read off `message`, because a hit found by
        `$search` carries a mutable id, and the caller already exchanged it for a stable one."""
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
