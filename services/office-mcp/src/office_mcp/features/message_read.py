"""Reading one Microsoft Teams message, from the handle a search result carries.

`message_search` cannot answer "what did they actually say". Graph's search index returns a
reduced `chatMessage` projection with **no `body`** — "The search Teams API doesn't return all
properties defined in chatMessage. You can use the Teams API to retrieve more details about any
single message" (https://learn.microsoft.com/en-us/graph/search-concept-chat-messages) — so a hit
is metadata plus a handle, and this is the module that turns the handle back into a message.

The handle is `message_search`'s contract, so `MessageHandle` and its parser live there, with the
search that mints them, and this module takes them from there rather than spelling the two shapes a
second time. `MessageSender` and `sender_of` arrive the same way and for the same reason: a message
means the same thing whichever of the two tools produced it, and that is a property of there being
one definition rather than of two agreeing.

What a read has to survive, all of it documented and none of it optional:

* **The body is Teams HTML.** `itemBody.contentType` is `html` or `text`, and the HTML is wrapper
  divs, `<at>` mention tags, `<emoji alt="👀">`, hostedContents `<img>` and `<attachment>`
  placeholders. Handing that to a model is a quality bug, so it is normalised to text here — the
  same normalisation `services/teams-mcp` ships merged, ported rather than reinvented, with one
  deliberate divergence: that port decides a message is an adaptive card when its *text* starts
  with `{` and contains `"type"`, which discards any message somebody pasted JSON into. The card
  signal here is attachment metadata instead, per `_is_card` below.
* **The sender is a different shape from search's.** A read gives `teamworkUserIdentity`
  (https://learn.microsoft.com/en-us/graph/api/resources/teamworkuseridentity): an id, an
  *optional* display name, and **no email property at all**. Search gives a mailbox-shaped
  `emailAddress`. Both go through `sender_of`, which is why a `sender` here has the same three
  fields as a search hit's, with different ones filled in.
* **System / event messages have no text anywhere.** `from` is null and `body.content` is the
  literal `<systemEventMessage/>`; the "Ada joined the chat" sentence is rendered by the Teams
  client and Graph never sends it (https://learn.microsoft.com/en-us/graph/system-messages). Search
  drops these; a read that lands on one has to say what the event *was*, from `eventDetail`.
* **Deleted and edited messages exist.** `deletedDateTime` and `lastEditedDateTime` are read-only
  properties of `chatMessage`; a tombstone must not be presented as live content.
* **`mentions[]` and `attachments[]` are the key to the body.** The body carries `<at id="0">` and
  `<attachment id="…">` placeholders whose meaning is in those collections, so both are returned
  resolved. A *card* is one of those attachments and nothing else: Graph marks it by the
  attachment's `contentType`, so that — never the shape of the body text — is what says a message
  is a card here.
"""

import html
import json
import re
from datetime import datetime
from typing import cast

from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.chats.item.messages.item.chat_message_item_request_builder import (
    ChatMessageItemRequestBuilder as ChatMessageRequestBuilder,
)
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.chat_message_attachment import ChatMessageAttachment
from msgraph.generated.models.chat_message_mention import ChatMessageMention
from msgraph.generated.models.chat_message_type import ChatMessageType
from msgraph.generated.teams.item.channels.item.messages.item.chat_message_item_request_builder import (  # noqa: E501
    ChatMessageItemRequestBuilder as ChannelMessageRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.features.message_search import (
    CHANNEL_PERMISSION,
    CHAT_PERMISSION,
    MessageHandle,
    MessageSender,
    sender_of,
)
from office_mcp.graph_client import graph_errors

# What the token exchange has to ask for: both, because the exchange happens before the tool sees
# its argument and so before anything knows which surface this call will read. Reading a message is
# `Chat.Read` in a chat and `ChannelMessage.Read.All` in a channel — the permissions are per surface
# (https://learn.microsoft.com/en-us/graph/api/chatmessage-get) — and `MessageHandle.permission` is
# what names the one a given read was actually made under.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

# `messageType` is an evolvable enum: without this header Graph answers `systemEventMessage` as
# `unknownFutureValue` (https://learn.microsoft.com/en-us/graph/api/resources/chatmessage). Nothing
# below *depends* on the type — a null `from` and a populated `eventDetail` identify a system
# message either way — but `chatEvent` and `typing` carry neither, and the type is the only thing
# that names them.
_PREFER_UNKNOWN_ENUMS = ("Prefer", "include-unknown-enum-members")

type _ChatMessageQuery = ChatMessageRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters
type _ChannelMessageQuery = (
    ChannelMessageRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters
)


class MessageMention(BaseModel):
    """One @-mention, resolved: the body only carries an `<at id="N">` placeholder."""

    text: str | None = Field(
        description=(
            "How the mention reads in the message, e.g. a person's display name or a team's name. "
            + "This is Microsoft's `mentionText`, and it is what the `@…` in `text` was rendered "
            + "from."
        )
    )
    user_id: str | None = Field(
        description=(
            "The mentioned person's Microsoft Entra object id, comparable against `user_id` from "
            + "get_me and the `mentions` parameter of search_messages. Null when the mention was "
            + "not a person — Teams also mentions teams, channels, chats, tags and everyone at "
            + "once — so a null here is not a failure to resolve a user."
        )
    )


class MessageAttachment(BaseModel):
    """One attachment. The body only carries an `<attachment id="…">` placeholder."""

    name: str | None = Field(
        description=(
            "The attachment's name, which is what `[attachment: …]` in `text` shows. Null for "
            + "attachments Teams gives no name, such as an adaptive card or a forwarded message."
        )
    )
    content_type: str | None = Field(
        description=(
            "Microsoft's `contentType`: `reference` for a link to a file, "
            + "`forwardedMessageReference` for a forwarded message, or a card type such as "
            + "`application/vnd.microsoft.card.adaptive` for an adaptive card and "
            + "`application/vnd.microsoft.card.codesnippet` for a code snippet. It says what the "
            + "attachment is, not what format the file is in — and it is the only thing that says "
            + "a message carries a card, which is why `[card]` in `text` comes from here."
        )
    )
    url: str | None = Field(
        description=(
            "Where the attachment's content lives, when Microsoft gave a URL. This connector does "
            + "not download attachments, and the URL may need Microsoft 365 credentials to open, "
            + "so treat it as a reference to show a person rather than something to fetch."
        )
    )


class TeamsMessage(BaseModel):
    """One Teams message, as fully as Microsoft Graph will describe it."""

    uri: str = Field(
        description=(
            "The handle this message was read from, in the canonical form search_messages emits. "
            + "Echoed so a message can be quoted, cached or re-read without reassembling it."
        )
    )
    message_id: str = Field(
        description=(
            "The message's Graph `id`. Unique only within its own chat, channel or reply thread, "
            + "so identify a message by `uri` rather than by this."
        )
    )
    chat_id: str | None = Field(
        description="The chat this message is in. Null for a channel message."
    )
    team_id: str | None = Field(description="The team, for a channel message. Null in a chat.")
    channel_id: str | None = Field(
        description="The channel, for a channel message. Null in a chat."
    )
    sender: MessageSender | None = Field(
        description=(
            "Who wrote the message, in the same shape search_messages reports. Null only when "
            + "nobody wrote it: Microsoft Graph sends no author for a system event message, which "
            + "`event` then describes. A read identifies a sender by Entra object id rather than "
            + "by email — the Teams identity Graph answers a read with carries no email address at "
            + "all — so `email` is normally null here even though search fills it in."
        )
    )
    text: str | None = Field(
        description=(
            "The message, as plain text. Teams HTML is normalised: mentions read as `@Name`, list "
            + "items as `- `, emoji as themselves, an inline image as `[image]`, an attachment as "
            + "`[attachment: name]` and a card as `[card]`, with every remaining tag removed and "
            + "every HTML entity decoded. Null when the message has no text of its own — a system "
            + "event, a deleted message, or a post that was only an image or a card. This is the "
            + "whole message, never abridged: text that happens to look like JSON or code is a "
            + "person's own words and is reported verbatim, and `[card]` appears only where "
            + "`attachments` names a card. This is the full body, not search's `summary` snippet."
        )
    )
    event: str | None = Field(
        description=(
            "What happened, when this is a system event message rather than something a person "
            + "wrote: `members joined`, `chat renamed`, `call ended` and so on, from Microsoft's "
            + "`eventDetail` type. Null for an ordinary message. Microsoft Graph does not send the "
            + "sentence Teams displays for these ('Ada joined the chat') — the Teams client writes "
            + "it — so this naming of the event is all there is, and there is no text to quote. "
            + "Who took part in the event is not returned by this connector."
        )
    )
    created_at: datetime | None = Field(description="When the message was sent.")
    last_edited_at: datetime | None = Field(
        description=(
            "When the message was last edited by its author, or null if it never was — this is "
            + "Microsoft's `lastEditedDateTime`, the property behind the 'Edited' flag in Teams. "
            + "Unlike `lastModifiedDateTime` it does not move when somebody adds a reaction."
        )
    )
    deleted_at: datetime | None = Field(
        description=(
            "When the message was deleted, or null if it is still live. When this is set, `text` "
            + "is null and the message's content is gone: say the message was deleted rather than "
            + "reporting it as empty."
        )
    )
    reply_to_id: str | None = Field(
        description=(
            "The id of the channel post this message replies to, for a reply in a channel thread; "
            + "null for a root post and for every chat message, which Teams does not thread."
        )
    )
    subject: str | None = Field(
        description="The message subject. Usually null: Teams sets one only on some channel posts."
    )
    importance: str | None = Field(
        description="`normal`, `high` or `urgent`, as the sender marked the message."
    )
    web_url: str | None = Field(
        description=(
            "A link that opens the message in Microsoft Teams. Populated for channel messages; "
            + "Graph gives chat messages no such link, so it is null there."
        )
    )
    mentions: list[MessageMention] = Field(
        description=(
            "Everyone and everything this message @-mentions, in the order Microsoft lists them. "
            + "Empty when it mentions nobody."
        )
    )
    attachments: list[MessageAttachment] = Field(
        description=(
            "What was attached: files, cards, code snippets, forwarded messages. Empty when "
            + "nothing was. The contents are not downloaded and a forwarded message's own body is "
            + "not unpacked."
        )
    )


async def read_message(client: GraphServiceClient, *, handle: MessageHandle) -> TeamsMessage:
    """The message `handle` addresses. One Graph request, whichever surface it lives on.

    `chatmessage-get` "doesn't support the OData query parameters", so there is no `$select` to
    narrow it with and no `$expand` to widen it: mentions and attachments arrive with the message.
    """
    with graph_errors():
        message = await _get(client, handle)

    assert message is not None, "Graph answered a message read with no message"
    return _message(message, handle)


async def _get(client: GraphServiceClient, handle: MessageHandle) -> ChatMessage | None:
    if handle.chat_id is not None:
        return await (
            client.chats.by_chat_id(handle.chat_id)
            .messages.by_chat_message_id(handle.message_id)
            .get(request_configuration=RequestConfiguration[_ChatMessageQuery](headers=_headers()))
        )
    assert handle.team_id is not None and handle.channel_id is not None, (
        "a handle addresses either a chat or a team channel"
    )
    return await (
        client.teams.by_team_id(handle.team_id)
        .channels.by_channel_id(handle.channel_id)
        .messages.by_chat_message_id(handle.message_id)
        .get(request_configuration=RequestConfiguration[_ChannelMessageQuery](headers=_headers()))
    )


def _headers() -> HeadersCollection:
    """A `HeadersCollection` of our own, carrying the `Prefer` header.

    Built per request on purpose: `RequestConfiguration.headers` defaults to a single
    `HeadersCollection` instance shared by every configuration in the process, so adding a header
    to the default would add it to every other Graph request this connector makes.
    """
    headers = HeadersCollection()
    headers.add(*_PREFER_UNKNOWN_ENUMS)
    return headers


def _message(message: ChatMessage, handle: MessageHandle) -> TeamsMessage:
    mentions = message.mentions or []
    attachments = message.attachments or []
    return TeamsMessage(
        uri=handle.uri,
        message_id=message.id or handle.message_id,
        chat_id=handle.chat_id,
        team_id=handle.team_id,
        channel_id=handle.channel_id,
        sender=sender_of(message.from_),
        text=_text(message, mentions=mentions, attachments=attachments),
        event=_event(message),
        created_at=message.created_date_time,
        last_edited_at=message.last_edited_date_time,
        deleted_at=message.deleted_date_time,
        reply_to_id=message.reply_to_id,
        subject=message.subject,
        # `ChatMessageImportance` subclasses `str`, so the member is its own wire value.
        importance=message.importance,
        web_url=message.web_url,
        mentions=[_mention(mention) for mention in mentions],
        attachments=[_attachment(attachment) for attachment in attachments],
    )


def _mention(mention: ChatMessageMention) -> MessageMention:
    mentioned = mention.mentioned
    user = mentioned.user if mentioned is not None else None
    return MessageMention(text=mention.mention_text, user_id=user.id if user is not None else None)


def _attachment(attachment: ChatMessageAttachment) -> MessageAttachment:
    return MessageAttachment(
        name=attachment.name,
        content_type=attachment.content_type,
        # `content` and `contentUrl` are documented as mutually exclusive, and `content` is a card
        # payload or a forwarded message's JSON rather than a location — so only the URL is a URL.
        url=attachment.content_url,
    )


# Every `eventMessageDetail` subtype is named `<what happened>EventMessageDetail`, and Microsoft
# lists all 31 (https://learn.microsoft.com/en-us/graph/system-messages) — so the `@odata.type` of
# the one Graph sent *is* the event. Reading the name is what makes this cover the subtypes
# Microsoft adds next as well as the ones that exist today; a table of the 31 would answer
# "unknown event" for the 32nd.
_EVENT_TYPE = re.compile(r"\A#?microsoft\.graph\.(.+?)EventMessageDetail\Z")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# What Teams renders itself and Graph describes to nobody: `chatEvent` and `typing` messages carry
# no `eventDetail`, and a `systemEventMessage` whose detail Graph omitted carries nothing either.
_UNDESCRIBED_EVENT = "a system event Microsoft Graph sent no detail for"


def _event(message: ChatMessage) -> str | None:
    """What this message is an event *of*, or None if a person wrote it.

    Three independent signals, because no one of them is reliable alone: `eventDetail` is only
    populated for `systemEventMessage`, `messageType` needs the `Prefer` header above to be legible
    at all, and a null `from` is what Graph actually sends for every one of them.
    """
    detail = message.event_detail
    if detail is not None:
        return _event_name(detail.odata_type) or _UNDESCRIBED_EVENT
    if message.from_ is None or (
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


# Teams HTML, in the order it has to be unwound. Everything here is a documented shape rather than
# a defensive guess: `services/teams-mcp` ships this same pipeline merged, and Microsoft's own
# examples are where the `<emoji alt>`, hostedContents `<img>` and `<attachment>` placeholder cases
# come from (https://learn.microsoft.com/en-us/graph/api/resources/chatmessage).
_PARAGRAPH_END = re.compile(r"</p\s*>", re.IGNORECASE)
_LINE_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LIST_ITEM_END = re.compile(r"</li\s*>", re.IGNORECASE)
_LIST_ITEM = re.compile(r"<li[^>]*>", re.IGNORECASE)
_MENTION_TAG = re.compile(r"<at([^>]*)>(.*?)</at\s*>", re.IGNORECASE | re.DOTALL)
_MENTION_INDEX = re.compile(r'\bid="(\d+)"', re.IGNORECASE)
# `<emoji id="1f440_eyes" alt="👀" title="Eyes">` — the character is in the attribute, so stripping
# the tag without reading it deletes the emoji from the message.
_EMOJI = re.compile(r'<(?:custom)?emoji[^>]*\balt="([^"]*)"[^>]*>', re.IGNORECASE)
_ATTACHMENT_TAG = re.compile(r'<attachment[^>]*\bid="([^"]+)"[^>]*>', re.IGNORECASE)
_IMAGE = re.compile(r"<img[^>]*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]*>")
_BLANK_LINES = re.compile(r"\n{3,}")

_ATTACHMENT = "[attachment]"
_CARD = "[card]"

# A card is *attachment metadata*, not something to sniff out of body text. Graph names it in
# `attachments[].contentType` — "If the attachment is a rich card, set the property to the rich card
# object" of `content` — and the documented value for an adaptive card is
# `application/vnd.microsoft.card.adaptive`, one of two card namespaces Teams publishes
# (https://learn.microsoft.com/en-us/graph/api/resources/chatmessageattachment,
# https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/cards-reference):
#
#     application/vnd.microsoft.card.adaptive              an adaptive card
#     application/vnd.microsoft.card.hero                  a hero card
#     application/vnd.microsoft.card.thumbnail             a thumbnail card
#     application/vnd.microsoft.card.receipt               a receipt card
#     application/vnd.microsoft.card.signin                a sign-in card
#     application/vnd.microsoft.card.codesnippet           a code snippet
#     application/vnd.microsoft.card.announcement          an announcement header
#     application/vnd.microsoft.teams.card.list            a list card
#     application/vnd.microsoft.teams.card.o365connector   a connector card for Microsoft 365 Groups
#
# The two prefixes are matched rather than those nine values enumerated, for the same reason
# `_EVENT_TYPE` reads an event's name instead of tabulating the 31 subtypes that exist today: the
# namespace is the documented shape, and Teams keeps adding card types to it.
_CARD_CONTENT_TYPES = ("application/vnd.microsoft.card.", "application/vnd.microsoft.teams.card.")


def _text(
    message: ChatMessage,
    *,
    mentions: list[ChatMessageMention],
    attachments: list[ChatMessageAttachment],
) -> str | None:
    """The message as plain text, or None when it has none.

    A deleted message has no content to normalise whatever `body` says, and returning what Graph
    happens to leave in a tombstone would present a deleted message as live text.
    """
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
    # A non-breaking space is what Teams puts between pasted words; a model reads it as a word
    # joiner rather than as the space it is meant to be.
    text = html.unescape(text).replace("\xa0", " ")
    text = _BLANK_LINES.sub("\n\n", text).strip()
    return _CARD if _is_card_payload(text, attachments) else text


def _mention_text(tag: re.Match[str], mention_texts: dict[int, str | None]) -> str:
    """`<at id="0">Ada Lovelace</at>` → `@Ada Lovelace`.

    The tag's `id` indexes `mentions[]` — Microsoft documents the correspondence — and that is the
    authority, because the element's own text is sometimes empty. Its text is the fallback, and if
    neither names anybody the mention is still marked: an `<at>` that vanished would read as the
    author addressing nobody, and a bare `<at id="0">` left in the text would be a key to nothing.
    """
    index = _MENTION_INDEX.search(tag.group(1))
    resolved = mention_texts.get(int(index.group(1))) if index is not None else None
    name = (resolved or _ANY_TAG.sub("", tag.group(2))).strip()
    return f"@{name}" if name else "[mention]"


def _attachment_marker(attachment: ChatMessageAttachment) -> str:
    """How one attachment reads where the body's `<attachment id="…">` placeholder sat.

    Teams gives a card no `name`, so a card would otherwise read as an anonymous `[attachment]`.
    Its `contentType` is what says it is a card, and that is where `[card]` comes from.
    """
    if attachment.name:
        return f"[attachment: {attachment.name}]"
    return _CARD if _is_card(attachment) else _ATTACHMENT


def _is_card(attachment: ChatMessageAttachment) -> bool:
    """Whether Graph marked this attachment as a card, by the only property that says so."""
    return (attachment.content_type or "").lower().startswith(_CARD_CONTENT_TYPES)


def _is_card_payload(text: str, attachments: list[ChatMessageAttachment]) -> bool:
    """Whether `text` is nothing but the payload of a card this message already carries.

    Teams sometimes leaves a card's own JSON in `body.content` instead of the
    `<attachment id="…">` placeholder, and handing a model a screenful of layout JSON spends its
    context on nothing. But *looking* like JSON is not evidence of a card — a developer pasting a
    config fragment or an API response into Teams writes a brace-and-`"type"` object too, and a
    guard that went by the shape of the text silently threw those messages away, in the one tool
    that is the only route to a message's text. So a body is only dropped when the message carries
    a card attachment whose `content` *is* that payload, compared parsed so that indentation and
    escaping do not decide it. Everything else is what somebody wrote, and is returned in full.
    """
    payload = _json(text)
    if payload is None:
        return False
    cards = (attachment for attachment in attachments if _is_card(attachment))
    return any(_json(card.content) == payload for card in cards)


def _json(value: str | None) -> object | None:
    """`value` parsed, or None when it is not a JSON object or array to begin with."""
    if value is None or not value.lstrip().startswith(("{", "[")):
        return None
    try:
        return cast("object", json.loads(value))
    except ValueError:
        return None
