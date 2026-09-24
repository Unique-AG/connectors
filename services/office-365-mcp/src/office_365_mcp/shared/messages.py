import html
import json
import re
from datetime import datetime
from typing import Self, cast

from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.chat_message_attachment import ChatMessageAttachment
from msgraph.generated.models.chat_message_from_identity_set import ChatMessageFromIdentitySet
from msgraph.generated.models.chat_message_mention import ChatMessageMention
from msgraph.generated.models.chat_message_reaction import ChatMessageReaction
from msgraph.generated.models.chat_message_type import ChatMessageType
from msgraph.generated.models.identity import Identity
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import MessageHandle

MAX_REPLIES_PER_POST = 10


class MessageSender(BaseModel):
    """Who sent a message, in whichever identity shape Microsoft Graph used."""

    display_name: str | None = Field(description="The sender's name as Teams shows it.")
    email: str | None = Field(
        description="The sender's email address, present only for search-hit results."
    )
    user_id: str | None = Field(
        description="The sender's Microsoft Entra object id, comparable across tools."
    )
    application_id: str | None = Field(
        description="The id of the sending application (bot, connector, or webhook), if any."
    )

    @classmethod
    def from_identity(cls, identity: ChatMessageFromIdentitySet | None) -> Self | None:
        if identity is None:
            return None
        user = identity.user
        application = identity.application
        mailbox_name, mailbox_address = _mailbox_identity(identity)
        named = _names_anybody(user) or _names_anybody(application)
        if not named and mailbox_name is None and mailbox_address is None:
            return None
        display_name = user.display_name if user is not None else None
        if display_name is None and application is not None:
            display_name = application.display_name
        return cls(
            display_name=_present(display_name) or mailbox_name,
            email=mailbox_address,
            user_id=user.id if user is not None else None,
            application_id=application.id if application is not None else None,
        )


class MessageMention(BaseModel):
    """One resolved @-mention from the message body."""

    text: str | None = Field(description="The mention's display text, for example a name.")
    user_id: str | None = Field(
        description="The mentioned person's Microsoft Entra object id, if the mention names one."
    )

    @classmethod
    def from_mention(cls, mention: ChatMessageMention) -> Self:
        mentioned = mention.mentioned
        user = mentioned.user if mentioned is not None else None
        return cls(text=mention.mention_text, user_id=user.id if user is not None else None)


class MessageAttachment(BaseModel):
    """One resolved attachment from the message body."""

    name: str | None = Field(description="The attachment's name, if it has one.")
    content_type: str | None = Field(
        description="Microsoft's content type for the attachment, such as a file or card type."
    )
    url: str | None = Field(
        description="Where the attachment's content lives, when Microsoft provides a URL."
    )

    @classmethod
    def from_attachment(cls, attachment: ChatMessageAttachment) -> Self:
        return cls(
            name=attachment.name,
            content_type=attachment.content_type,
            url=attachment.content_url,
        )


class MessageReaction(BaseModel):
    """One reaction to a message: what was used, who added it, and when."""

    reaction_type: str | None = Field(
        description="What was used to react: an emoji, `custom`, or a legacy reaction name."
    )
    user_id: str | None = Field(description="The reactor's Microsoft Entra object id, if known.")
    display_name: str | None = Field(description="The reactor's name as Teams shows it, if known.")
    created_at: datetime | None = Field(description="When this reaction was added.")

    @classmethod
    def from_reaction(cls, reaction: ChatMessageReaction) -> Self:
        identity = reaction.user.user if reaction.user is not None else None
        return cls(
            reaction_type=reaction.reaction_type,
            user_id=identity.id if identity is not None else None,
            display_name=identity.display_name if identity is not None else None,
            created_at=reaction.created_date_time,
        )


class TeamsMessage(BaseModel):
    """One Teams message, as fully as Microsoft Graph will describe it."""

    uri: str = Field(description="The handle this message was read from.")
    message_id: str = Field(description="The message's Graph id.")
    chat_id: str | None = Field(description="The chat this message is in, or null for channels.")
    team_id: str | None = Field(description="The team, for channel messages, or null for chats.")
    channel_id: str | None = Field(
        description="The channel, for channel messages, or null for chats."
    )
    sender: MessageSender | None = Field(
        description="Who wrote the message, or null for system event messages."
    )
    text: str | None = Field(
        description="The message as plain text, with Teams HTML normalized to readable text."
    )
    event: str | None = Field(
        description="What happened, when this message is a system event; null otherwise."
    )
    created_at: datetime | None = Field(description="When the message was sent.")
    last_edited_at: datetime | None = Field(
        description="When the message was last edited, or null if never."
    )
    deleted_at: datetime | None = Field(
        description="When the message was deleted, or null if it is still live."
    )
    reply_to_id: str | None = Field(
        description="The id of the channel post this message replies to, or null otherwise."
    )
    subject: str | None = Field(description="The message subject, usually null.")
    importance: str | None = Field(
        description="`normal`, `high` or `urgent`, as the sender marked it."
    )
    web_url: str | None = Field(
        description="A link to open the message in Microsoft Teams, or null for chats."
    )
    mentions: list[MessageMention] = Field(
        description="Everyone and everything this message @-mentions."
    )
    attachments: list[MessageAttachment] = Field(
        description="What was attached to this message: files, cards, or forwarded messages."
    )
    reactions: list[MessageReaction] = Field(description="Who reacted to this message, and how.")

    @classmethod
    def from_message(cls, message: ChatMessage, *, handle: MessageHandle) -> Self:
        mentions = message.mentions or []
        attachments = message.attachments or []
        return cls(
            uri=handle.uri,
            message_id=message.id or handle.message_id,
            chat_id=handle.chat_id,
            team_id=handle.team_id,
            channel_id=handle.channel_id,
            sender=MessageSender.from_identity(message.from_),
            text=_text(message, mentions=mentions, attachments=attachments),
            event=event_of(message),
            created_at=message.created_date_time,
            last_edited_at=message.last_edited_date_time,
            deleted_at=message.deleted_date_time,
            reply_to_id=message.reply_to_id or handle.reply_to_id,
            subject=message.subject,
            importance=message.importance,
            web_url=message.web_url,
            mentions=[MessageMention.from_mention(mention) for mention in mentions],
            attachments=[
                MessageAttachment.from_attachment(attachment) for attachment in attachments
            ],
            reactions=[
                MessageReaction.from_reaction(reaction) for reaction in (message.reactions or [])
            ],
        )


_EVENT_TYPE = re.compile(r"\A#?microsoft\.graph\.(.+?)EventMessageDetail\Z")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_UNDESCRIBED_EVENT = "a system event Microsoft Graph sent no detail for"


def event_of(message: ChatMessage) -> str | None:
    detail = message.event_detail
    if detail is not None:
        return _event_name(detail.odata_type) or _UNDESCRIBED_EVENT
    if MessageSender.from_identity(message.from_) is None or (
        message.message_type is not None and message.message_type != ChatMessageType.Message
    ):
        return _UNDESCRIBED_EVENT
    return None


def _event_name(odata_type: str | None) -> str | None:
    if odata_type is None:
        return None
    matched = _EVENT_TYPE.match(odata_type)
    if matched is None:
        return None
    return _CAMEL_BOUNDARY.sub(" ", matched.group(1)).lower()


def _names_anybody(identity: Identity | None) -> bool:
    return identity is not None and (
        identity.id is not None or _present(identity.display_name) is not None
    )


def _mailbox_identity(identity: ChatMessageFromIdentitySet) -> tuple[str | None, str | None]:
    extra = cast("dict[str, object]", identity.additional_data)
    mailbox = extra.get("emailAddress")
    if not isinstance(mailbox, dict):
        return (None, None)
    fields_ = cast("dict[str, object]", mailbox)
    return (_string(fields_.get("name")), _string(fields_.get("address")))


def _string(value: object) -> str | None:
    return _present(value) if isinstance(value, str) else None


def _present(value: str | None) -> str | None:
    return value if value is not None and value.strip() else None


_PARAGRAPH_END = re.compile(r"</p\s*>", re.IGNORECASE)
_LINE_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LIST_ITEM_END = re.compile(r"</li\s*>", re.IGNORECASE)
_LIST_ITEM = re.compile(r"<li[^>]*>", re.IGNORECASE)
_MENTION_TAG = re.compile(r"<at([^>]*)>(.*?)</at\s*>", re.IGNORECASE | re.DOTALL)
_MENTION_INDEX = re.compile(r'\bid="(\d+)"', re.IGNORECASE)
_EMOJI = re.compile(r'<(?:custom)?emoji[^>]*\balt="([^"]*)"[^>]*>', re.IGNORECASE)
_ATTACHMENT_TAG = re.compile(r'<attachment[^>]*\bid="([^"]+)"[^>]*>', re.IGNORECASE)
_IMAGE = re.compile(r"<img[^>]*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]*>")
_BLANK_LINES = re.compile(r"\n{3,}")

_ATTACHMENT = "[attachment]"
_CARD = "[card]"

_CARD_CONTENT_TYPES = ("application/vnd.microsoft.card.", "application/vnd.microsoft.teams.card.")


def _text(
    message: ChatMessage,
    *,
    mentions: list[ChatMessageMention],
    attachments: list[ChatMessageAttachment],
) -> str | None:
    if message.deleted_date_time is not None:
        return None
    body = message.body
    if body is None or body.content is None:
        return None
    if body.content_type != BodyType.Html:
        return body.content.strip() or None
    return _from_html(body.content, mentions=mentions, attachments=attachments) or None


def _from_html(
    content: str,
    *,
    mentions: list[ChatMessageMention],
    attachments: list[ChatMessageAttachment],
) -> str:
    mention_texts = {
        mention.id: mention.mention_text for mention in mentions if mention.id is not None
    }
    markers = {
        attachment.id: _attachment_marker(attachment)
        for attachment in attachments
        if attachment.id is not None
    }

    text = _PARAGRAPH_END.sub("\n", content)
    text = _LINE_BREAK.sub("\n", text)
    text = _LIST_ITEM_END.sub("\n", text)
    text = _LIST_ITEM.sub("- ", text)
    text = _MENTION_TAG.sub(lambda tag: _mention_text(tag, mention_texts), text)
    text = _EMOJI.sub(lambda tag: tag.group(1), text)
    text = _ATTACHMENT_TAG.sub(lambda tag: markers.get(tag.group(1), _ATTACHMENT), text)
    text = _IMAGE.sub("[image]", text)
    text = _ANY_TAG.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = _BLANK_LINES.sub("\n\n", text).strip()
    return _CARD if _is_card_payload(content, text, attachments) else text


def _mention_text(tag: re.Match[str], mention_texts: dict[int, str | None]) -> str:
    index = _MENTION_INDEX.search(tag.group(1))
    resolved = mention_texts.get(int(index.group(1))) if index is not None else None
    name = (resolved or _ANY_TAG.sub("", tag.group(2))).strip()
    return f"@{name}" if name else "[mention]"


def _attachment_marker(attachment: ChatMessageAttachment) -> str:
    if attachment.name:
        return f"[attachment: {attachment.name}]"
    return _CARD if _is_card(attachment) else _ATTACHMENT


def _is_card(attachment: ChatMessageAttachment) -> bool:
    return (attachment.content_type or "").lower().startswith(_CARD_CONTENT_TYPES)


def _is_card_payload(
    content: str, rewritten: str, attachments: list[ChatMessageAttachment]
) -> bool:
    bodies = [
        parsed
        for parsed in (_json(content), _json(html.unescape(content)), _json(rewritten))
        if parsed is not None
    ]
    cards = (attachment for attachment in attachments if _is_card(attachment))
    return any(_json(card.content) in bodies for card in cards)


def _json(value: str | None) -> object | None:
    if value is None or not value.lstrip().startswith(("{", "[")):
        return None
    try:
        return cast("object", json.loads(value))
    except ValueError:
        return None
