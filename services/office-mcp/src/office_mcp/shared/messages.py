"""What a Teams message is: the shape three tools answer it in, and the HTML it is unwound from.

Graph's sender shapes, every field of all three optional: `teamworkUserIdentity`, which has no email
property at all (https://learn.microsoft.com/en-us/graph/api/resources/teamworkuseridentity); an
application identity for a bot, connector or outgoing webhook
(https://learn.microsoft.com/en-us/graph/api/resources/teamworkapplicationidentity); and the
mailbox-shaped `emailAddress` a search hit carries, because Teams messages are indexed out of the
substrate mailbox.

Microsoft documents the identity set as null for a deleted message and for one the Teams internal
system sent. Such a message's `body.content` is the literal `<systemEventMessage/>`, and the "Ada
joined the chat" sentence is the Teams client's own
(https://learn.microsoft.com/en-us/graph/system-messages). A channel listing has to drop these
client-side: Graph offers no server-side `messageType` filter on that collection.
"""

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
from msgraph.generated.models.chat_message_type import ChatMessageType
from msgraph.generated.models.identity import Identity
from pydantic import BaseModel, Field

from office_mcp.shared.handles import MessageHandle

# How many of a post's replies a channel browse returns, and so how far back a reply is reachable in
# this connector at all. `$expand=replies` brings back up to 200 replies per post, and 50 posts of
# 200 replies is a response no caller has a budget for.
#
# This window is the end of the line rather than a first page. Graph expands up to 200 replies
# before it pages them, so a thread it paged comes back full to this window, and following its
# cursor costs a request per post against a channel that allows the whole app one a second. A reply
# older than this window has no route to its full text here: a search can find it and report
# Microsoft's snippet, but Graph addresses a reply under the post it answers and the search index
# does not name that post.
MAX_REPLIES_PER_POST = 10


class MessageSender(BaseModel):
    """Who sent a message, in whichever identity shape Graph used.

    Three shapes: search hits carry Exchange-style `emailAddress` (name and address), Teams reads
    return `teamworkUserIdentity` (id and optional name, no email), and a bot, connector or
    outgoing webhook is an application identity (id and optional name). Which fields are filled
    says which shape Graph answered with. A null is not evidence that the sender has no name, no
    address or no id.
    """

    display_name: str | None = Field(
        description=(
            "The sender's name as Teams shows it. Genuinely absent on some messages from external "
            + "and federated users. A null is not an anonymous sender."
        )
    )
    email: str | None = Field(
        description=(
            "The sender's email address. Present when Graph answered with the mailbox-shaped "
            + "identity (search hits). Null for the Teams identity, which has no email property. "
            + "Compare `user_id` when this is null."
        )
    )
    user_id: str | None = Field(
        description=(
            "The sender's Microsoft Entra object id from the Teams-shaped identity. This is what "
            + "the `mentions` search parameter takes. The only sender field safe to compare "
            + "against ids from other tools in chats and channels. Null for applications and when "
            + "Graph gave an email address."
        )
    )
    application_id: str | None = Field(
        description=(
            "The id of the application that sent the message — a bot, a connector or an outgoing "
            + "webhook. Null for a message a person sent. Not interchangeable with `user_id`, and "
            + "the `mentions` search parameter does not accept it."
        )
    )

    @classmethod
    def from_identity(cls, identity: ChatMessageFromIdentitySet | None) -> Self | None:
        """The sender, or None when Graph named nobody.

        Decided on the identity Graph named, not on the fields above: every one of those is
        optional, so an identity carrying an id or a name is a sender whatever else it left blank,
        while the identity object being present says nothing, because Graph sends empty ones.
        """
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
            # `displayName` is documented Optional and Graph does send it blank; an empty name would
            # read as an unnamed sender rather than as the "Graph did not say" the id fields cover.
            display_name=_present(display_name) or mailbox_name,
            email=mailbox_address,
            user_id=user.id if user is not None else None,
            application_id=application.id if application is not None else None,
        )


class MessageMention(BaseModel):
    """One @-mention.

    The body carries an `<at id="N">` placeholder; this is the resolved mention.
    """

    text: str | None = Field(
        description=(
            "How the mention reads in the message, e.g. a person's name or a team's name. "
            + "Microsoft's `mentionText`. This is what the `@…` in `text` was rendered from."
        )
    )
    user_id: str | None = Field(
        description=(
            "The mentioned person's Entra object id. Comparable against `user_id` from get_me and "
            + "the `mentions` search parameter. Null when not a person (Teams also mentions teams, "
            + "channels, tags, etc)."
        )
    )

    @classmethod
    def from_mention(cls, mention: ChatMessageMention) -> Self:
        mentioned = mention.mentioned
        user = mentioned.user if mentioned is not None else None
        return cls(text=mention.mention_text, user_id=user.id if user is not None else None)


class MessageAttachment(BaseModel):
    """One attachment.

    The body carries an `<attachment id="…">` placeholder; this is the resolved attachment.
    """

    name: str | None = Field(
        description=(
            "The attachment's name, shown as `[attachment: …]` in `text`. Null for attachments "
            + "without names, like cards or forwarded messages."
        )
    )
    content_type: str | None = Field(
        description=(
            "Microsoft's `contentType`: `reference` for file links, `forwardedMessageReference` "
            + "for forwarded messages, or card types like "
            + "`application/vnd.microsoft.card.adaptive`. It says what the attachment is, not the "
            + "file format. It is the only signal that a message carries a card, so `[card]` in "
            + "`text` comes from here."
        )
    )
    url: str | None = Field(
        description=(
            "Where the attachment's content lives when Microsoft provides a URL. This connector "
            + "does not download. The URL may need Microsoft 365 credentials to open, so treat it "
            + "as a reference to show."
        )
    )

    @classmethod
    def from_attachment(cls, attachment: ChatMessageAttachment) -> Self:
        return cls(
            name=attachment.name,
            content_type=attachment.content_type,
            # `content` and `contentUrl` are documented mutually exclusive, and `content` is a card
            # payload or a forwarded message's JSON rather than a location.
            url=attachment.content_url,
        )


class TeamsMessage(BaseModel):
    """One Teams message, as fully as Microsoft Graph will describe it."""

    uri: str = Field(
        description=(
            "The handle this message was read from, in the form read_message takes. Echoed so "
            + "messages can be quoted, cached or re-read without reassembling. For a reply in a "
            + "channel thread this is its only handle, because Microsoft addresses a reply under "
            + "its parent post and search cannot express that shape."
        )
    )
    message_id: str = Field(
        description=(
            "The message's Graph `id`. Unique only within its chat, channel or reply thread. Use "
            + "`uri` to identify globally."
        )
    )
    chat_id: str | None = Field(
        description="The chat this message is in. Null for channel messages."
    )
    team_id: str | None = Field(description="The team, for channel messages. Null for chats.")
    channel_id: str | None = Field(description="The channel, for channel messages. Null for chats.")
    sender: MessageSender | None = Field(
        description=(
            "Who wrote the message, in the same shape search_messages reports. Null only when "
            + "nobody wrote it: Graph sends no author for system event messages, which `event` "
            + "then describes. Reads identify senders by Entra id rather than email—the Teams "
            + "identity has no email address at all—so `email` is normally null here."
        )
    )
    text: str | None = Field(
        description=(
            "The message as plain text. Teams HTML is normalised: mentions as `@Name`, list items "
            + "as `- `, emoji as themselves, inline images as `[image]`, attachments as "
            + "`[attachment: name]`, cards as `[card]`, all tags removed, HTML entities decoded. "
            + "Null when no text of its own—system events, deleted messages, posts that were only "
            + "images or cards. This is the whole message, never abridged. Text that looks like "
            + "JSON or code is a person's words and is reported in full. `[card]` appears only "
            + "where `attachments` names a card."
        )
    )
    event: str | None = Field(
        description=(
            "What happened when this is a system event message: `members joined`, `chat renamed`, "
            + "`call ended`, etc., from Microsoft's `eventDetail` type. Null for ordinary "
            + "messages. Graph does not send the sentence Teams displays—the client writes it—so "
            + "this naming is all there is: report it, and do not invent the wording. "
            + "Participant details are not returned."
        )
    )
    created_at: datetime | None = Field(description="When the message was sent.")
    last_edited_at: datetime | None = Field(
        description=(
            "When last edited by the author, or null if never. Microsoft's `lastEditedDateTime`, "
            + "the property behind Teams' 'Edited' flag. Unlike `lastModifiedDateTime`, it does "
            + "not change when reactions are added."
        )
    )
    deleted_at: datetime | None = Field(
        description=(
            "When deleted, or null if live. When set, `text` is null and content is gone. Do not "
            + "return the tombstone body as live content. Say the message was deleted, do not "
            + "report it as empty."
        )
    )
    reply_to_id: str | None = Field(
        description=(
            "The id of the channel post this message replies to, for replies in channel threads. "
            + "Null for root posts and all chat messages (Teams does not thread chats)."
        )
    )
    subject: str | None = Field(
        description="The message subject. Usually null: Teams sets it only on some channel posts."
    )
    importance: str | None = Field(
        description="`normal`, `high` or `urgent`, as marked by the sender."
    )
    web_url: str | None = Field(
        description=(
            "A link to open the message in Microsoft Teams. Set for channel messages. Null for "
            + "chats."
        )
    )
    mentions: list[MessageMention] = Field(
        description=(
            "Everyone and everything this message @-mentions, in Microsoft's order. Empty when "
            + "none."
        )
    )
    attachments: list[MessageAttachment] = Field(
        description=(
            "What was attached: files, cards, code snippets, forwarded messages. Empty when "
            + "nothing. Contents are not downloaded. Forwarded messages are not unpacked."
        )
    )

    @classmethod
    def from_message(cls, message: ChatMessage, *, handle: MessageHandle) -> Self:
        """`message` as this connector reports, addressed by `handle`."""
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
            # The handle is the fallback rather than the source: it names a parent only for a reply,
            # while Graph sets `replyToId` on every message in a channel thread.
            reply_to_id=message.reply_to_id or handle.reply_to_id,
            subject=message.subject,
            # `ChatMessageImportance` subclasses `str`, so the member is its own wire value.
            importance=message.importance,
            web_url=message.web_url,
            mentions=[MessageMention.from_mention(mention) for mention in mentions],
            attachments=[
                MessageAttachment.from_attachment(attachment) for attachment in attachments
            ],
        )


# Every eventMessageDetail subtype is named <what happened>EventMessageDetail, so reading the name
# covers what Microsoft adds next. A table of the 31 types today answers "unknown" for the 32nd.
_EVENT_TYPE = re.compile(r"\A#?microsoft\.graph\.(.+?)EventMessageDetail\Z")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# `chatEvent` and `typing` messages carry no `eventDetail`, and Graph omits it on some others.
_UNDESCRIBED_EVENT = "a system event Microsoft Graph sent no detail for"


def event_of(message: ChatMessage) -> str | None:
    """What this message is an event of, or None if a person wrote it.

    Three signals, none reliable alone, because Graph omits `eventDetail` on some events and names
    no author on others. The sender signal is `MessageSender.from_identity` rather than `from` being
    null, so `sender` being null and this saying what happened cannot disagree.
    """
    detail = message.event_detail
    if detail is not None:
        return _event_name(detail.odata_type) or _UNDESCRIBED_EVENT
    if MessageSender.from_identity(message.from_) is None or (
        message.message_type is not None and message.message_type != ChatMessageType.Message
    ):
        return _UNDESCRIBED_EVENT
    return None


def _event_name(odata_type: str | None) -> str | None:
    """`#microsoft.graph.membersJoinedEventMessageDetail` → `members joined`."""
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
    """The `emailAddress` a search hit carries instead of a Teams identity, as (name, address).

    `POST /search/query` answers with `from: {"emailAddress": {"name": ..., "address": ...}}` where
    the Teams APIs answer with `from: {"user": {...}}`. The SDK's identity set has no field for the
    mailbox shape, so it arrives in `additional_data`, untyped, hence the narrowing here.
    """
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


# Teams HTML, in the order it has to be unwound. The `<emoji alt>`, hostedContents `<img>` and
# `<attachment>` placeholders come from Microsoft's own examples
# (https://learn.microsoft.com/en-us/graph/api/resources/chatmessage).
_PARAGRAPH_END = re.compile(r"</p\s*>", re.IGNORECASE)
_LINE_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LIST_ITEM_END = re.compile(r"</li\s*>", re.IGNORECASE)
_LIST_ITEM = re.compile(r"<li[^>]*>", re.IGNORECASE)
_MENTION_TAG = re.compile(r"<at([^>]*)>(.*?)</at\s*>", re.IGNORECASE | re.DOTALL)
_MENTION_INDEX = re.compile(r'\bid="(\d+)"', re.IGNORECASE)
# The character is in the `alt` attribute, so stripping the tag deletes it from the message.
_EMOJI = re.compile(r'<(?:custom)?emoji[^>]*\balt="([^"]*)"[^>]*>', re.IGNORECASE)
_ATTACHMENT_TAG = re.compile(r'<attachment[^>]*\bid="([^"]+)"[^>]*>', re.IGNORECASE)
_IMAGE = re.compile(r"<img[^>]*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]*>")
_BLANK_LINES = re.compile(r"\n{3,}")

_ATTACHMENT = "[attachment]"
_CARD = "[card]"

# A card is *attachment metadata*, not something to sniff out of body text: Graph names it in
# `attachments[].contentType`, whose documented adaptive-card value is
# `application/vnd.microsoft.card.adaptive`
# (https://learn.microsoft.com/en-us/graph/api/resources/chatmessageattachment,
# https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/cards-reference).
# The two namespaces are matched rather than today's nine values enumerated, because Teams keeps
# adding card types to them.
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
    # Teams puts a non-breaking space between pasted words, and a model reads it as a word joiner.
    text = html.unescape(text).replace("\xa0", " ")
    text = _BLANK_LINES.sub("\n\n", text).strip()
    return _CARD if _is_card_payload(content, text, attachments) else text


def _mention_text(tag: re.Match[str], mention_texts: dict[int, str | None]) -> str:
    """`<at id="0">Ada Lovelace</at>` → `@Ada Lovelace`. The tag's `id` indexes `mentions[]` and is
    the authority; the element's own text is the fallback, because it is sometimes empty."""
    index = _MENTION_INDEX.search(tag.group(1))
    resolved = mention_texts.get(int(index.group(1))) if index is not None else None
    name = (resolved or _ANY_TAG.sub("", tag.group(2))).strip()
    return f"@{name}" if name else "[mention]"


def _attachment_marker(attachment: ChatMessageAttachment) -> str:
    """How one attachment reads where the body's `<attachment id="…">` placeholder sat. Teams gives
    cards no `name`, so `[card]` comes from the `contentType` instead."""
    if attachment.name:
        return f"[attachment: {attachment.name}]"
    return _CARD if _is_card(attachment) else _ATTACHMENT


def _is_card(attachment: ChatMessageAttachment) -> bool:
    return (attachment.content_type or "").lower().startswith(_CARD_CONTENT_TYPES)


def _is_card_payload(
    content: str, rewritten: str, attachments: list[ChatMessageAttachment]
) -> bool:
    """Whether the body is nothing but the payload of a card this message already carries.

    Teams sometimes leaves card JSON in `body.content` instead of `<attachment id="…">`. Parsed JSON
    is compared, and only against a card attachment's own `content`: looking like JSON is not
    evidence, because a developer pasting an API response writes brace-and-type too.

    Three spellings of the body, because none of them matches every shape Teams sends. `content` is
    the body before the rewrites above, which delete markup and turn a non-breaking space into a
    plain space; its unescaped form covers the one difference Graph itself makes, escaping a body
    and never `attachment.content`; `rewritten` uncovers a payload Teams wrapped in its own markup.
    """
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
