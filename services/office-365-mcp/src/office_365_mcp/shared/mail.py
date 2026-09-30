import re
from typing import Literal, Self

from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.followup_flag import FollowupFlag
from msgraph.generated.models.followup_flag_status import FollowupFlagStatus
from msgraph.generated.models.importance import Importance
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
    "importance",
    "flag",
    "categories",
    "isDraft",
    "sender",
    "replyTo",
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


def _spelled(value: FollowupFlagStatus | Importance | None) -> str | None:
    return None if value is None else str.__str__(value)


class FlagMoment(BaseModel):
    date_time: str | None = Field(
        description=(
            "The date and time in the zone that `time_zone` names, with no offset, for example "
            "`2017-08-29T04:00:00.0000000`."
        )
    )
    time_zone: str | None = Field(
        description=(
            "The time zone of `date_time`, for example `Pacific Standard Time`. The value is "
            "null if Microsoft 365 reports none."
        )
    )

    @classmethod
    def from_moment(cls, moment: DateTimeTimeZone | None) -> Self | None:
        if moment is None:
            return None
        return cls(date_time=moment.date_time, time_zone=moment.time_zone)


class MailFlag(BaseModel):
    status: str | None = Field(
        description=(
            "The follow-up status that Microsoft 365 reports: `notFlagged`, `flagged`, or "
            "`complete`. The value is null if it reports none."
        )
    )
    start: FlagMoment | None = Field(
        description=(
            "When the follow-up begins. The value is null if Microsoft 365 reports no start "
            "time for the flag."
        )
    )
    due: FlagMoment | None = Field(
        description=(
            "When the follow-up is due. The value is null if Microsoft 365 reports no due time "
            "for the flag."
        )
    )
    completed: FlagMoment | None = Field(
        description=(
            "When the user marked the follow-up complete. The value is null if Microsoft 365 "
            "reports no completion time for the flag."
        )
    )

    @classmethod
    def from_flag(cls, flag: FollowupFlag | None) -> Self | None:
        if flag is None:
            return None
        return cls(
            status=_spelled(flag.flag_status),
            start=FlagMoment.from_moment(flag.start_date_time),
            due=FlagMoment.from_moment(flag.due_date_time),
            completed=FlagMoment.from_moment(flag.completed_date_time),
        )


class MailSummary(BaseModel):
    uri: str = Field(
        description="A handle for this message; pass it to outlook_read_mail to read the body."
    )
    subject: str | None = Field(description="The subject line, or null if none was set.")
    preview: str | None = Field(
        description=f"The first {PREVIEW_CHARACTERS} characters of the body as plain text."
    )
    sender: MailAddress | None = Field(description="Who sent the message, or null if none.")
    sent_by: MailAddress | None = Field(
        description=(
            "The account that sent the message, or null if none. This differs from `sender` if "
            "a delegate sent the message for the owner."
        )
    )
    to: list[MailAddress] = Field(description="The To recipients.")
    reply_to: list[MailAddress] = Field(
        description=(
            "The addresses that receive a reply. The sender chose these addresses, so they can "
            "differ from `sender`. The list is empty if the sender chose none."
        )
    )
    received_at: str | None = Field(
        description="When the mailbox received the message, in ISO-8601 UTC, or null for a draft."
    )
    is_read: bool | None = Field(description="Whether the message is marked read.")
    has_attachments: bool | None = Field(description="Whether Graph reports attachments.")
    importance: str | None = Field(
        description=(
            "The importance of the message: `low`, `normal`, or `high`. The value is null if "
            "Microsoft 365 reports none."
        )
    )
    flag: MailFlag | None = Field(
        description=(
            "The follow-up flag of the message, or null if Microsoft 365 reports none. The "
            "`status` is `notFlagged` if the message has no flag."
        )
    )
    categories: list[str] = Field(
        description=(
            "The names of the Outlook categories on the message. The list is empty if the "
            "message has none."
        )
    )
    is_draft: bool | None = Field(
        description=(
            "Whether the message is a draft. A message is a draft until someone sends it. The "
            "value is null if Microsoft 365 reports none."
        )
    )
    folder_id: str | None = Field(description="The Graph id of the folder holding the message.")
    web_link: str | None = Field(description="A link that opens the message in Outlook on the web.")

    @classmethod
    def from_message(cls, message: Message, *, message_id: str) -> Self:
        return cls(
            uri=MailMessageHandle(message_id).uri,
            subject=message.subject,
            preview=message.body_preview,
            sender=MailAddress.from_recipient(message.from_),
            sent_by=MailAddress.from_recipient(message.sender),
            to=MailAddress.each_of(message.to_recipients),
            reply_to=MailAddress.each_of(message.reply_to),
            received_at=(
                None
                if message.received_date_time is None
                else message.received_date_time.isoformat()
            ),
            is_read=message.is_read,
            has_attachments=message.has_attachments,
            importance=_spelled(message.importance),
            flag=MailFlag.from_flag(message.flag),
            categories=message.categories or [],
            is_draft=message.is_draft,
            folder_id=message.parent_folder_id,
            web_link=message.web_link,
        )
