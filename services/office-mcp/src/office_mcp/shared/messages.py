"""What a Teams message is: the shape it is answered in, and the HTML it is unwound from.

Two tools answer with a message or part of one — a search hit and a single read — and Graph hands
each of them a different projection of the same thing. A message therefore has to mean the same
thing whichever tool produced it, and that is a property of there being one definition rather than
of two agreeing: a message a search found and the same message read by handle are the same type,
normalised by the same function, with the same sender shape and the same test for "did a person
write this".

What the normalisation has to survive, all of it documented and none of it optional:

* **The body is Teams HTML.** `itemBody.contentType` is `html` or `text`, and the HTML is wrapper
  divs, `<at>` mention tags, `<emoji alt="👀">`, hostedContents `<img>` and `<attachment>`
  placeholders. Handing that to a model is a quality bug, so it is normalised to text here — the
  same normalisation `services/teams-mcp` ships merged, ported rather than reinvented, with one
  deliberate divergence: that port decides a message is an adaptive card when its *text* starts
  with `{` and contains `"type"`, which discards any message somebody pasted JSON into. The card
  signal here is attachment metadata instead, per `_is_card` below.
* **The sender arrives in three shapes.** Every Teams read API answers with `teamworkUserIdentity`
  (https://learn.microsoft.com/en-us/graph/api/resources/teamworkuseridentity): an id, an
  *optional* display name, and **no email property at all**. Search answers with a mailbox-shaped
  `emailAddress`, because Teams messages are indexed out of the substrate mailbox. A bot, a
  connector or an outgoing webhook arrives as an application identity
  (https://learn.microsoft.com/en-us/graph/api/resources/teamworkapplicationidentity), whose
  display name is again *optional* and whose id is not. All three go through `sender_of`, which is
  why a sender is the same four fields whichever shape Graph used, with different ones filled in —
  and why which fields are populated says which shape Graph answered with rather than saying the
  sender has no name, no address or no id.
* **Every field of a sender is optional; the identity Graph named is not.** So `sender_of` decides
  on what the identity holds rather than on the fields it produced: an identity carrying an id or a
  name is a sender, whatever else it left blank. Deciding on the output instead discards every
  actor Graph names in a field this projection does not read — an application whose display name is
  blank loses its id and its message together. Deciding on the identity object's mere presence is
  the opposite error: Graph sends empty ones, and reading those as senders answers with a hit whose
  every field is null.
* **System / event messages have no sender and no text.** Microsoft documents the identity set as
  null "for a message that has been deleted or sent by the Microsoft Teams internal system; for
  example, event messages for addition of members", and such a message's `body.content` is the
  literal `<systemEventMessage/>`; the "Ada joined the chat" sentence is rendered by the Teams
  client and Graph never sends it (https://learn.microsoft.com/en-us/graph/system-messages). A
  search drops these — the `messageType` and `eventDetail` properties that would name the event
  are not in its projection, which leaves the missing sender as the only thing that says so — and
  a read that lands on one has to say what the event *was*, from `eventDetail`. Two behaviours
  over one question, which is why `event_of` is the one place that answers it rather than each
  tool having its own opinion about what counts as a message somebody wrote.
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

from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.chat_message_attachment import ChatMessageAttachment
from msgraph.generated.models.chat_message_from_identity_set import ChatMessageFromIdentitySet
from msgraph.generated.models.chat_message_mention import ChatMessageMention
from msgraph.generated.models.chat_message_type import ChatMessageType
from msgraph.generated.models.identity import Identity
from pydantic import BaseModel, Field

from office_mcp.shared.handles import MessageHandle


class MessageSender(BaseModel):
    """Who sent a message, from whichever identity shape Graph used.

    Three shapes. Teams messages are indexed out of the substrate mailbox, so a search hit carries
    an Exchange-style `emailAddress` (a name and an address), while every Teams read API returns a
    `teamworkUserIdentity` (an id and an optional display name, and no email at all); a bot, a
    connector or an outgoing webhook is an application identity (an id and an optional display
    name). Which fields are populated therefore says which shape Graph answered with, and a null is
    not evidence that the sender has no name, no address or no id.
    """

    display_name: str | None = Field(
        description=(
            "The sender's name as Teams shows it. Microsoft documents this as optional and it is "
            + "genuinely absent on some messages, including messages from external and federated "
            + "users — a null is not an anonymous sender."
        )
    )
    email: str | None = Field(
        description=(
            "The sender's email address. Present when Graph answered with the mailbox-shaped "
            + "identity that search hits normally carry, and null otherwise; the Teams identity "
            + "has no email property at all, so compare `user_id` when this is null."
        )
    )
    user_id: str | None = Field(
        description=(
            "The sender's Microsoft Entra object id, when Graph answered with the Teams-shaped "
            + "identity. This is the value the `mentions` search parameter takes, and the only "
            + "sender field safe to compare against ids from other tools. Null for a message sent "
            + "by an application (a bot or a connector), and null when Graph gave an email "
            + "address instead."
        )
    )
    application_id: str | None = Field(
        description=(
            "The id of the application that sent the message — a bot, a connector or an outgoing "
            + "webhook. Microsoft documents this id as always present on an application identity, "
            + "where the display name is optional, so it is the one field that names such a sender "
            + "in every case. Null for a message a person sent. It is not interchangeable with "
            + "`user_id`, and the `mentions` search parameter does not accept it: that parameter "
            + "matches on user ids alone."
        )
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


def sender_of(identity: ChatMessageFromIdentitySet | None) -> MessageSender | None:
    """The sender, or None when Graph named no sender at all.

    One function over all three identity shapes, because a search hit and a read of the same
    message must report the same sender.

    The decision is made on the identity Graph named rather than on the fields below, because every
    one of those is optional: an identity carrying an id or a name is a sender, whatever else it
    left blank. What the presence of the identity *object* says is nothing — Graph sends an empty
    one — so a sender is only as real as what is inside it. A null `from`, and an identity set
    naming nobody, is how Graph sends a deleted message and a Teams internal system message, so
    None is also the signal a search filters those hits out by.
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
    return MessageSender(
        # Empty strings are collapsed to null: `displayName` is documented Optional and Graph does
        # send it blank, and a name that is present-but-empty reads as an unnamed sender rather
        # than as the "Graph did not say" that the id fields are there to work around.
        display_name=_present(display_name) or mailbox_name,
        email=mailbox_address,
        user_id=user.id if user is not None else None,
        application_id=application.id if application is not None else None,
    )


def message_of(message: ChatMessage, *, handle: MessageHandle) -> TeamsMessage:
    """`message` as this connector reports a Teams message, addressed by `handle`.

    One function rather than one per Graph projection: a `chatMessage` carries the same fields
    whichever collection it came out of, so every tool that answers with a whole message answers
    with the same shape, normalised the same way, because it is the same function rather than two
    that agree.
    """
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
        event=event_of(message),
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


def event_of(message: ChatMessage) -> str | None:
    """What this message is an event *of*, or None if a person wrote it.

    Three independent signals, because no one of them is reliable alone: `eventDetail` is only
    populated for `systemEventMessage`, `messageType` needs a `Prefer` header on the request to be
    legible at all, and a null `from` is what Graph actually sends for every one of them.

    This is also the test for "is this a message somebody wrote", which is the question every tool
    that filters system messages out of a collection has to ask the same way a read does — or the
    two disagree about what a message is.
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


def _names_anybody(identity: Identity | None) -> bool:
    """Whether Graph put anything identifying in this identity.

    An id or a name is somebody. An identity holding neither is not a sender Graph declined to
    name; it is Graph sending the object and naming nobody in it, which reads the same as the
    property being absent.
    """
    return identity is not None and (
        identity.id is not None or _present(identity.display_name) is not None
    )


def _mailbox_identity(identity: ChatMessageFromIdentitySet) -> tuple[str | None, str | None]:
    """The `emailAddress` a search hit carries instead of a Teams identity, as (name, address).

    Search reads Teams messages out of the substrate mailbox, so `POST /search/query` answers with
    `from: {"emailAddress": {"name": ..., "address": ...}}` where the Teams APIs answer with
    `from: {"user": {...}}`. The SDK's identity set has no field for the mailbox shape, so it
    arrives in `additional_data` — untyped by construction, hence the narrowing here.

    Either half is None unless it says something, so that a mailbox object holding nothing but
    blanks names nobody here too.
    """
    extra = cast("dict[str, object]", identity.additional_data)
    mailbox = extra.get("emailAddress")
    if not isinstance(mailbox, dict):
        return (None, None)
    fields_ = cast("dict[str, object]", mailbox)
    return (_string(fields_.get("name")), _string(fields_.get("address")))


def _string(value: object) -> str | None:
    """`value` when it is a string that says something, else None."""
    return _present(value) if isinstance(value, str) else None


def _present(value: str | None) -> str | None:
    """`value` if it says anything, else None."""
    return value if value is not None and value.strip() else None


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
