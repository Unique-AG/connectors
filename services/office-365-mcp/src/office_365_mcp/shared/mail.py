"""This module defines the shape of an Outlook message: the fields that every reader requests,
and the shape that every reader answers in.

Four tools find or list mail, and one tool reads it. All four agree here on one shape, because
no tool decides this on its own. The difference is not cosmetic. A summary with a preview from
one tool, and none from another, reads to the caller as "this message has no text." An address
that two tools normalize two different ways compares as unequal to itself.

`SUMMARY_FIELDS` is the `$select` list that all of them use. This one set turns a hit from search
and a row from a folder listing into the same shape.

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
# `Mail.ReadBasic` withholds. This is why the reading tools declare `Mail.Read` instead: a hit
# list with no snippet is a list of subjects that a model cannot triage.
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

# This is Microsoft's own documented length for `bodyPreview`. It is named here because two
# tools quote it to a model. If the number drifts in just one tool, that tool promises something
# that the other does not.
PREVIEW_CHARACTERS = 255

# One SMTP address, with no display name and no list. Exchange either rejects
# `Ada <ada@x.invalid>`, or reads the whole string as a name without a warning.
ONE_ADDRESS = re.compile(r"\A[^\s<>,;:\"@]+@[^\s<>,;:\"@]+\Z")

# Shared by outlook_draft_mail and outlook_draft_reply. These are the only two tools that attach
# a file.
MAX_ATTACHMENTS = 10

# This is Microsoft's ceiling for a `fileAttachment` added through one `POST .../attachments`
# call. It is measured against the decoded bytes.
MAX_ATTACHMENT_BYTES = 3 * 1024 * 1024

# This is Microsoft's ceiling for a single attachment on a message, inline or not. A file from
# `MAX_ATTACHMENT_BYTES` up to this line attaches through an upload session instead.
MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION = 150 * 1024 * 1024

# Reused with no change by both attaching tools, so the text stays the same for both.
ATTACHMENTS_FIELD: str = (
    f"Files to attach, at most {MAX_ATTACHMENTS}. Each entry has Graph's own small-attachment "
    + "shape: `name` (the file name shown to the recipient), `content_type` (a MIME type, for "
    + "example `application/pdf`), and `content_bytes` (the file's own bytes, base64-encoded — "
    + "`contentBytes` on the wire). The DECODED size of each entry must be under "
    + f"{MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION // (1024 * 1024)} MB. This is Microsoft's own "
    + "ceiling for a single attachment on an Outlook item "
    + "(https://learn.microsoft.com/en-us/graph/outlook-large-attachments). A file under "
    + f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB attaches directly. A larger file attaches "
    + "through Microsoft's own upload session instead, and this connector does that step for you "
    + "— this argument takes the same shape either way. Omit this argument, or pass an empty "
    + "list, for a draft with no attachment."
)


# The well-known folder names that Graph accepts in a URL path are seven of the seventeen total.
# These are the ones that a person says out loud. They do not depend on locale, so `inbox`
# reaches the Inbox of a mailbox in any language.
#
# The other ten are left out on purpose. `conflicts`, `localfailures`, `serverfailures`, and
# `syncissues` are Outlook's own sync diagnostics, not mail. `msgfolderroot` and `searchfolders`
# are parent folders, not message folders. `recoverableitemsdeletions` is the purge bin.
# Microsoft says it "isn't visible in any Outlook email client". `outbox` holds a message only
# for the seconds before it leaves, so a listing of it is a race. `conversationhistory` holds
# Skype and Teams history. `scheduled` exists only for Outlook on iOS.
#
# A tool reaches a folder outside this list only by its handle from outlook_browse_folders,
# never by name. A custom folder's name belongs to the user. A match of that name by string is
# how a tool files mail into the wrong place.
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
    """This is one small file that a caller wants attached, exactly as the schema takes it. It
    is Graph's own `fileAttachment` shape, minus the parts that Graph fills in itself (`id`,
    `size`, `isInline`)."""

    name: str = Field(
        min_length=1, description="This is the file name, shown to the recipient exactly as given."
    )
    content_type: str = Field(
        min_length=1, description="This is the file's MIME type, for example `application/pdf`."
    )
    content_bytes: str = Field(
        min_length=1,
        description=(
            "These are the file's own bytes, base64-encoded — Graph's own `contentBytes` shape."
        ),
    )


class MailAttachmentSummary(BaseModel):
    """This is one attachment, exactly as a tool left it. Name, MIME type, and decoded size are
    inert data that Graph stores with no change, rather than something that Graph decides —
    unlike a recipient, which Graph can resolve or drop. So there is no discrepancy here for a
    read-back to catch, and a caller can trust this."""

    name: str = Field(description="This is the file name, exactly as given.")
    content_type: str = Field(description="This is the MIME type, exactly as given.")
    size: int = Field(description="This is the decoded size of the attachment, in bytes.")


def decode_attachment(content_bytes: str) -> bytes | None:
    """This function returns the raw bytes that `content_bytes` decodes to. It returns `None`
    when the value is not valid base64."""
    try:
        return base64.b64decode(content_bytes, validate=True)
    except ValueError:
        return None


class MailAddress(BaseModel):
    """This is one person or mailbox on a message, exactly as Graph's `emailAddress` gives it."""

    name: str | None = Field(
        description=(
            "This is the display name on the message. Whoever sent the message wrote this "
            + "name, so on inbound mail it is text that a stranger chose, and it never matches "
            + "anybody's entry in the directory. This field is null when Graph recorded none."
        )
    )
    address: str | None = Field(
        description=(
            "This is the SMTP address. Use this address to compare, to quote, and to reuse. "
            + "This field is null only for a message that Graph recorded no address for. This "
            + "happens on some drafts."
        )
    )

    @classmethod
    def from_recipient(cls, recipient: Recipient | None) -> Self | None:
        """This function returns the address, or `None` when Graph named nobody. This happens on
        a draft with an empty `to`, or on a message whose sender Graph did not record."""
        if recipient is None or recipient.email_address is None:
            return None
        return cls(name=recipient.email_address.name, address=recipient.email_address.address)

    @classmethod
    def from_email_address(cls, address: EmailAddress | None) -> Self | None:
        """Graph does not wrap a calendar's `owner` in a `recipient`. It is a bare `emailAddress`
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
    """This is one message, exactly as every finder and lister answers it: enough detail to
    choose from, never the whole body."""

    uri: str = Field(
        description=(
            "This is a handle for this exact message, `outlook:///messages/{id}` with the id "
            + "percent-encoded. Pass this handle, with no change, to outlook_read_mail for the "
            + "body. It stays valid when the message is filed into another folder. Outlook does "
            + "this on its own, through inbox rules and retention."
        )
    )
    subject: str | None = Field(
        description=(
            "This is the subject line. This field is null when the message was sent without one."
        )
    )
    preview: str | None = Field(
        description=(
            f"This is the first {PREVIEW_CHARACTERS} characters of the body, as plain text, from "
            + "the very top. On a reply, this is usually the quoted header block, and not what "
            + "the sender wrote. If this preview does not answer the question, that is not proof "
            + "that the message does not answer it either. Read the message first. This field is "
            + "null under a permission that withholds it."
        )
    )
    sender: MailAddress | None = Field(
        description=(
            "This is who sent the message. This field is null for a message that Graph recorded "
            + "no sender for."
        )
    )
    to: list[MailAddress] = Field(
        description=(
            "These are the To recipients, and only the To recipients. Cc and Bcc are not read "
            + "here — outlook_read_mail reports Cc. An empty list means that Graph returned "
            + "none, not that nobody was addressed."
        )
    )
    received_at: str | None = Field(
        description=(
            "This is when the mailbox received the message, in ISO-8601 format, in UTC. This "
            + "field is null on a draft, because a draft was never received. Compare and sort "
            + "messages on this timestamp, not on anything in the subject."
        )
    )
    is_read: bool | None = Field(
        description=(
            "This says whether the message is marked read. This field is null when Graph did "
            + "not say."
        )
    )
    has_attachments: bool | None = Field(
        description=(
            "This says whether Graph reports attachments. No tool here returns attachment bytes "
            + "or names. This value is false for a message whose only attachment is an inline "
            + "image."
        )
    )
    folder_id: str | None = Field(
        description=(
            "This is the Graph id of the folder that holds the message. This id is opaque. No "
            + "tool here turns it into a folder name. outlook_browse_folders reports the id and "
            + "the name together."
        )
    )
    web_link: str | None = Field(
        description=(
            "This is Graph's own link that opens the message in Outlook on the web, passed "
            + "through exactly as Graph gave it. This connector never builds or repairs this "
            + "link. Microsoft changed the format in 2025, so a hand-built link opens the wrong "
            + "item, or no item."
        )
    )

    @classmethod
    def from_message(cls, message: Message, *, message_id: str) -> Self:
        """`message_id` is passed in, instead of read off `message`. A hit found by `$search`
        carries a mutable id, and the caller already exchanged it for a stable one."""
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
