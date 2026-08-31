"""The handle grammar: every shape this connector mints, the parser, and the speller.

Two schemes, one per product. `teams:///` addresses Microsoft Teams, and `outlook:///` addresses
a mailbox. If a mail shape used the Teams scheme, it has to answer `MessageHandle.permission`
below, and that answer reaches `teams_read_message`'s declared permissions and, from there, the
consent screen of every `teams` deployment. The scheme is the cheapest place to keep the two
products apart.

This is the only module that spells or parses these URIs. tests/test_layering.py enforces that.
A second speller does not look like a disagreement. It looks like a handle that one tool produced
and another answers 404 to.

Three of the five shapes are Graph's three ways to address a Teams message
(https://learn.microsoft.com/en-us/graph/api/chatmessage-get). The reply shape is the one a
search cannot mint. Graph addresses a reply *under* its parent post, and the search projection
carries no `replyToId`. So a channel hit that is really a reply becomes the plain channel shape
instead, and Graph answers 404 to that. Only `teams_browse_channel` walks a channel post by post
and knows each reply's parent.

A meeting is addressed by join URL, because that is the only route Graph gives a delegated
caller from chat to meeting. No chat id, topic, or date turns into one. A transcript is addressed
by the two ids that its content path is built from, and not by that join URL. So reading one does
not repeat the resolve, spend a second request and permission on it, and answer a 403 that can be
about either.

The family name is the first segment for this reason. Nesting `{x}` under both `meetings` and
`transcripts` in one URI, like `teams:///meetings/{x}/transcripts/{y}`, makes `{x}` ambiguous. It
reads as a join URL in one shape and as a meeting id in another. A parser cannot tell them apart.

Every segment is percent-encoded, because join URLs carry `:`, `/`, `?`, `&`, `%`, `#` and Teams ids
carry `:` and `@` (`19:...@thread.v2`). The parser rejects half-encoded input, so a hand-spelled
handle comes back as "not a handle" rather than as a truncated URL Graph ignores.

Every `outlook:///` family is one segment, because Outlook addresses each of these by a single
opaque id. There are four families rather than one. Graph gives them all one id space, but this
connector keeps them apart: a draft is a message with `isDraft` set. Splitting them into four
families keeps a message that a reader found from being spelled as a draft and handed to the tool
that sends.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

# One per surface, and which surface a handle addresses is the whole of what picks between them.
CHAT_PERMISSION = "Chat.Read"
CHANNEL_PERMISSION = "ChannelMessage.Read.All"


@dataclass(frozen=True, slots=True)
class MessageHandle:
    message_id: str
    chat_id: str | None = None
    team_id: str | None = None
    channel_id: str | None = None
    reply_to_id: str | None = None

    @property
    def permission(self) -> str:
        return CHAT_PERMISSION if self.chat_id is not None else CHANNEL_PERMISSION

    @property
    def uri(self) -> str:
        if self.chat_id is not None:
            return f"teams:///chats/{_segment(self.chat_id)}/messages/{_segment(self.message_id)}"
        assert self.team_id is not None and self.channel_id is not None, (
            "a handle addresses either a chat or a team channel"
        )
        channel = f"teams:///teams/{_segment(self.team_id)}/channels/{_segment(self.channel_id)}"
        if self.reply_to_id is not None:
            return (
                f"{channel}/messages/{_segment(self.reply_to_id)}"
                + f"/replies/{_segment(self.message_id)}"
            )
        return f"{channel}/messages/{_segment(self.message_id)}"


@dataclass(frozen=True, slots=True)
class MeetingHandle:
    join_web_url: str

    @property
    def uri(self) -> str:
        return f"teams:///meetings/{_segment(self.join_web_url)}"


@dataclass(frozen=True, slots=True)
class TranscriptHandle:
    """This identifies a transcript by the two ids that Graph's content path is built from.
    Graph's own `transcriptContentUrl` is not used, because the published samples are malformed
    (`…/transcripts/('…')/content`)."""

    meeting_id: str
    transcript_id: str

    @property
    def uri(self) -> str:
        return f"teams:///transcripts/{_segment(self.meeting_id)}/{_segment(self.transcript_id)}"


@dataclass(frozen=True, slots=True)
class MailMessageHandle:
    message_id: str

    @property
    def uri(self) -> str:
        return f"outlook:///messages/{_segment(self.message_id)}"


@dataclass(frozen=True, slots=True)
class MailFolderHandle:
    """This identifies a mail folder by its Graph id. That id is what reaches a folder that no
    well-known name covers.

    This is its own family, because Outlook's well-known names (`inbox`, `sentitems`, …) are a
    closed vocabulary that a tool spells as a `Literal`. An id is the other half of that argument.
    """

    folder_id: str

    @property
    def uri(self) -> str:
        return f"outlook:///folders/{_segment(self.folder_id)}"


@dataclass(frozen=True, slots=True)
class MailDraftHandle:
    """This identifies a draft that this connector composed. It is the only thing the sending
    tool accepts.

    Graph gives a draft the same id space as any other message. Keeping the families apart stops
    a message that a reader found from being spelled as a draft. This is what makes "send the
    mail you just wrote" expressible, and "send that mail I found" unspellable.
    """

    draft_id: str

    @property
    def uri(self) -> str:
        return f"outlook:///drafts/{_segment(self.draft_id)}"


@dataclass(frozen=True, slots=True)
class MailRuleHandle:
    rule_id: str

    @property
    def uri(self) -> str:
        return f"outlook:///rules/{_segment(self.rule_id)}"


# Ids are matched as "anything but a separator", because the spellers above percent-encode each one.
_CHAT_HANDLE = re.compile(r"\Ateams:///chats/([^/]+)/messages/([^/]+)\Z")
_CHANNEL_HANDLE = re.compile(r"\Ateams:///teams/([^/]+)/channels/([^/]+)/messages/([^/]+)\Z")
_REPLY_HANDLE = re.compile(
    r"\Ateams:///teams/([^/]+)/channels/([^/]+)/messages/([^/]+)/replies/([^/]+)\Z"
)
_MEETING_HANDLE = re.compile(r"\Ateams:///meetings/([^/]+)\Z")
_TRANSCRIPT_HANDLE = re.compile(r"\Ateams:///transcripts/([^/]+)/([^/]+)\Z")
_MAIL_MESSAGE_HANDLE = re.compile(r"\Aoutlook:///messages/([^/]+)\Z")
_MAIL_FOLDER_HANDLE = re.compile(r"\Aoutlook:///folders/([^/]+)\Z")
_MAIL_DRAFT_HANDLE = re.compile(r"\Aoutlook:///drafts/([^/]+)\Z")
_MAIL_RULE_HANDLE = re.compile(r"\Aoutlook:///rules/([^/]+)\Z")


def message_handle(uri: str) -> MessageHandle | None:
    """`uri` as a message handle, or None if it is not one this connector can read. None rather than
    an exception carrying advice: what to tell a caller about a malformed handle is each reader
    tool's own wording."""
    chat = _CHAT_HANDLE.match(uri)
    if chat is not None:
        chat_id, message_id = (unquote(part) for part in chat.groups())
        return _message_handle(MessageHandle(message_id=message_id, chat_id=chat_id))
    reply = _REPLY_HANDLE.match(uri)
    if reply is not None:
        team_id, channel_id, root_id, message_id = (unquote(part) for part in reply.groups())
        return _message_handle(
            MessageHandle(
                message_id=message_id,
                team_id=team_id,
                channel_id=channel_id,
                reply_to_id=root_id,
            )
        )
    channel = _CHANNEL_HANDLE.match(uri)
    if channel is not None:
        team_id, channel_id, message_id = (unquote(part) for part in channel.groups())
        return _message_handle(
            MessageHandle(message_id=message_id, team_id=team_id, channel_id=channel_id)
        )
    return None


def meeting_handle(uri: str) -> MeetingHandle | None:
    match = _MEETING_HANDLE.match(uri)
    if match is None:
        return None
    join_web_url = unquote(match.group(1))
    return MeetingHandle(join_web_url) if join_web_url.strip() else None


def transcript_handle(uri: str) -> TranscriptHandle | None:
    match = _TRANSCRIPT_HANDLE.match(uri)
    if match is None:
        return None
    meeting_id, transcript_id = (unquote(part) for part in match.groups())
    if not meeting_id.strip() or not transcript_id.strip():
        return None
    return TranscriptHandle(meeting_id, transcript_id)


def mail_message_handle(uri: str) -> MailMessageHandle | None:
    message_id = _single_id(_MAIL_MESSAGE_HANDLE, uri)
    return None if message_id is None else MailMessageHandle(message_id)


def mail_folder_handle(uri: str) -> MailFolderHandle | None:
    folder_id = _single_id(_MAIL_FOLDER_HANDLE, uri)
    return None if folder_id is None else MailFolderHandle(folder_id)


def mail_draft_handle(uri: str) -> MailDraftHandle | None:
    draft_id = _single_id(_MAIL_DRAFT_HANDLE, uri)
    return None if draft_id is None else MailDraftHandle(draft_id)


def mail_rule_handle(uri: str) -> MailRuleHandle | None:
    rule_id = _single_id(_MAIL_RULE_HANDLE, uri)
    return None if rule_id is None else MailRuleHandle(rule_id)


def meeting_uri_for(join_web_url: str | None) -> str | None:
    """Meeting handle for `join_web_url`, or None when Graph gave none."""
    if join_web_url is None or not join_web_url.strip():
        return None
    return MeetingHandle(join_web_url).uri


def _message_handle(handle: MessageHandle) -> MessageHandle | None:
    """The handle, unless a segment decoded to nothing, because `%20` is not an id."""
    ids = (
        handle.message_id,
        handle.chat_id,
        handle.team_id,
        handle.channel_id,
        handle.reply_to_id,
    )
    if any(value is not None and not value.strip() for value in ids):
        return None
    return handle


def _single_id(pattern: re.Pattern[str], uri: str) -> str | None:
    """The one id a single-segment handle carries, or None when `uri` is not that shape.

    None for a segment that decoded to nothing too, because `%20` is not an id — the same rule
    that `_message_handle` applies to the Teams shapes.
    """
    match = pattern.match(uri)
    if match is None:
        return None
    value = unquote(match.group(1))
    return value if value.strip() else None


def _segment(value: str) -> str:
    return quote(value, safe="")
