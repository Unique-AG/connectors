import html
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Self, cast

from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.chats.item.messages.item.chat_message_item_request_builder import (
    ChatMessageItemRequestBuilder as ChatMessageRequestBuilder,
)
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.chat_message_attachment import ChatMessageAttachment
from msgraph.generated.models.chat_message_from_identity_set import ChatMessageFromIdentitySet
from msgraph.generated.models.chat_message_importance import ChatMessageImportance
from msgraph.generated.models.chat_message_mention import ChatMessageMention
from msgraph.generated.models.chat_message_mentioned_identity_set import (
    ChatMessageMentionedIdentitySet,
)
from msgraph.generated.models.chat_message_reaction import ChatMessageReaction
from msgraph.generated.models.chat_message_type import ChatMessageType
from msgraph.generated.models.identity import Identity
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.teamwork_user_identity_type import TeamworkUserIdentityType
from msgraph.generated.teams.item.channels.item.messages.item.chat_message_item_request_builder import (  # noqa: E501
    ChatMessageItemRequestBuilder as ChannelMessageRequestBuilder,
)
from msgraph.generated.teams.item.channels.item.messages.item.replies.item.chat_message_item_request_builder import (  # noqa: E501
    ChatMessageItemRequestBuilder as ChannelReplyRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_step
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.handles import MessageHandle
from office_365_mcp.shared.identity import ENTRA_OBJECT_ID_PATTERN
from office_365_mcp.shared.prose import cut_for_a_question


class MessageSender(BaseModel):
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


STEP_CHAT_MESSAGE = "chat_message"
STEP_CHANNEL_MESSAGE = "channel_message"
STEP_CHANNEL_REPLY = "channel_reply"

_PREFER_UNKNOWN_ENUMS = ("Prefer", "include-unknown-enum-members")

type _ChatMessageQuery = ChatMessageRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters
type _ChannelMessageQuery = (
    ChannelMessageRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters
)
type _ChannelReplyQuery = ChannelReplyRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters


async def get_message(client: GraphServiceClient, handle: MessageHandle) -> ChatMessage | None:
    if handle.chat_id is not None:
        with graph_step(STEP_CHAT_MESSAGE):
            return await (
                client.chats.by_chat_id(handle.chat_id)
                .messages.by_chat_message_id(handle.message_id)
                .get(
                    request_configuration=RequestConfiguration[_ChatMessageQuery](
                        headers=_headers()
                    )
                )
            )
    assert handle.team_id is not None and handle.channel_id is not None, (
        "a handle addresses either a chat or a team channel"
    )
    messages = (
        client.teams.by_team_id(handle.team_id).channels.by_channel_id(handle.channel_id).messages
    )
    if handle.reply_to_id is not None:
        with graph_step(STEP_CHANNEL_REPLY):
            return await (
                messages.by_chat_message_id(handle.reply_to_id)
                .replies.by_chat_message_id1(handle.message_id)
                .get(
                    request_configuration=RequestConfiguration[_ChannelReplyQuery](
                        headers=_headers()
                    )
                )
            )
    with graph_step(STEP_CHANNEL_MESSAGE):
        return await messages.by_chat_message_id(handle.message_id).get(
            request_configuration=RequestConfiguration[_ChannelMessageQuery](headers=_headers())
        )


def _headers() -> HeadersCollection:
    headers = HeadersCollection()
    headers.add(*_PREFER_UNKNOWN_ENUMS)
    return headers


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


class Mention(BaseModel, frozen=True):
    user_id: str = Field(
        pattern=ENTRA_OBJECT_ID_PATTERN,
        description=(
            "The Microsoft Entra object id of the person to mention, as a GUID. Copy it from the "
            + "`user_id` of get_me, of a teams_list_chat_members row, of a teams_list_chats "
            + "member, or of a message `sender`. Never build it from a name or an email address."
        ),
    )
    name: str = Field(
        min_length=1,
        description=(
            "The text that Teams shows for the mention, usually the display name of the person. "
            + "Use the `display_name` that comes from the same result as the `user_id`."
        ),
    )


def outgoing_message(
    text: str,
    *,
    mentions: Sequence[Mention] = (),
    importance: ChatMessageImportance | None = None,
    subject: str | None = None,
) -> ChatMessage:
    if not mentions:
        return ChatMessage(
            body=ItemBody(content=text, content_type=BodyType.Text),
            importance=importance,
            subject=subject,
        )
    tags = " ".join(
        f'<at id="{index}">{html.escape(mention.name)}</at>'
        for index, mention in enumerate(mentions)
    )
    return ChatMessage(
        body=ItemBody(
            content=f"{tags} {html.escape(text).replace('\n', '<br>')}",
            content_type=BodyType.Html,
        ),
        mentions=[
            ChatMessageMention(
                id=index,
                mention_text=mention.name,
                mentioned=ChatMessageMentionedIdentitySet(
                    user=Identity(
                        id=mention.user_id,
                        display_name=mention.name,
                        additional_data={
                            "userIdentityType": TeamworkUserIdentityType.AadUser.value
                        },
                    )
                ),
            )
            for index, mention in enumerate(mentions)
        ],
        importance=importance,
        subject=subject,
    )


type ChatImportance = Literal["normal", "high", "urgent"]

type ChannelImportance = Literal["normal", "high"]


@dataclass(frozen=True, slots=True)
class SendWords:
    verb: str
    agree: str
    decline: str
    nothing_sent: str
    cannot_be_recalled: str


CHAT_SEND = SendWords(
    verb="Send",
    agree="send",
    decline="do not send",
    nothing_sent="Nothing was sent.",
    cannot_be_recalled="This cannot be recalled once sent.",
)

CHANNEL_POST = SendWords(
    verb="Post",
    agree="post",
    decline="do not post",
    nothing_sent="Nothing was posted.",
    cannot_be_recalled="This cannot be recalled once posted.",
)

CHAT_ID_FIELD: str = (
    "The chat to post to, as the `chat_id` that teams_list_chats reported, for example "
    + "`19:...@thread.v2`. It is not a `teams:///` handle."
)

MESSAGE_FIELD: str = (
    "The text of the message, as plain text. Do not put HTML or mention markup in this text, "
    + "because this tool writes all the markup itself."
)

MENTIONS_FIELD: str = (
    "The people to @mention, one entry for each person. With an empty list, the message "
    + "mentions nobody."
)

CHAT_IMPORTANCE_FIELD: str = (
    "The importance of the new message: `normal`, `high`, or `urgent`. Set this parameter only "
    + "when the user asks for an importance."
)

CHAT_SUBJECT_FIELD: str = (
    "The subject of the new chat message, as plain text. Omit this parameter to send the message "
    + "with no subject."
)

TEAM_ID_FIELD: str = (
    "The team that holds the channel, as the `team_id` that teams_list_my_teams reported. It is "
    + "a GUID, not a `teams:///` handle."
)

CHANNEL_ID_FIELD: str = (
    "The channel to post to, as the `channel_id` that teams_list_channels reported for this team, "
    + "for example `19:...@thread.tacv2`. It is not a `teams:///` handle."
)

REPLY_TO_ID_FIELD: str = (
    "The `message_id` of the channel post to reply to, as teams_browse_channel or "
    + "teams_read_message reports it. Give the id of a post, never the id of a reply. To answer a "
    + "reply, give the `reply_to_id` of that reply. Omit this parameter to start a new post."
)

CHANNEL_SUBJECT_FIELD: str = (
    "The subject of the new channel post, as plain text. Omit this parameter to post the message "
    + "with no subject. This tool refuses a subject together with `reply_to_id`."
)

CHANNEL_IMPORTANCE_FIELD: str = (
    "The importance of the new message: `normal` or `high`. Set this parameter only when the user "
    + "asks for an importance."
)


def subject_on_a_reply(tool: str) -> str:
    return (
        f"{tool} received both `subject` and `reply_to_id`. This tool sets a subject only on a new "
        + "channel post, never on a reply. To reply in the thread, omit `subject`. To start a new "
        + f"post with a subject, omit `reply_to_id`. {CHANNEL_POST.nothing_sent} If you call this "
        + "tool again with the same arguments, the call will fail the same way."
    )


def send_question(
    words: SendWords,
    message: str,
    destination: str,
    mentions: Sequence[Mention],
    *,
    subject: str | None,
    importance: ChatImportance | None,
) -> str:
    named = ", ".join(repr(cut_for_a_question(mention.name)) for mention in mentions)
    mentioned = f" It mentions {named}." if mentions else ""
    details = [
        text
        for text in (
            None if subject is None else f"the subject {cut_for_a_question(subject)!r}",
            None if importance is None else f"{importance} importance",
        )
        if text is not None
    ]
    marked = f" with {' and '.join(details)}" if details else ""
    return (
        f"{words.verb} {cut_for_a_question(message)!r}{marked} {destination} now?"
        + f"{mentioned} {words.cannot_be_recalled}"
    )


def send_binding(
    destination: Sequence[str],
    message: str,
    mentions: Sequence[Mention],
    *,
    subject: str | None,
    importance: ChatImportance | None,
) -> str:
    return confirmation_id_for(
        *destination,
        message,
        *mention_fields(mentions),
        repr(subject),
        repr(importance),
    )


def mention_fields(mentions: Sequence[Mention]) -> tuple[str, ...]:
    return (
        str(len(mentions)),
        *(field for mention in mentions for field in (mention.user_id, mention.name)),
    )
