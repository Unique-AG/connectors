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

# One SMTP address and nothing else: no display name, no angle brackets, no second address. A model
# that packs `Ada <ada@x.invalid>` or `a@x.invalid, b@y.invalid` into one string names somebody
# Exchange either rejects or silently reads as a name, and both are quietly wrong. Four tools take
# a list of addresses from a model — two draft mail, two create an event — and each one refuses in
# its own words. What none of them decides on its own is which strings are one address.
ONE_ADDRESS = re.compile(r"\A[^\s<>,;:\"@]+@[^\s<>,;:\"@]+\Z")


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
        """The same shape from a bare `emailAddress`, or None when Graph named nobody.

        Graph wraps a mail recipient in a `recipient` and does not wrap a calendar's `owner`
        (https://learn.microsoft.com/en-us/graph/api/resources/calendar): that property is an
        `emailAddress` on its own.
        """
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
