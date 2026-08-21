"""The `teams:///` handle grammar: every shape this connector mints, the parser, and the speller.

A handle is how one tool's answer becomes another tool's argument, and that works only while
exactly one definition of each shape exists. Two modules spelling `teams:///meetings/…` would
silently disagree. So the grammar lives here rather than in tool files, and this is the only module
that spells or parses these URIs (enforced by tests/test_layering.py).

## The five shapes, and why they are five

Three of them are Graph's three ways to address a Teams message
(https://learn.microsoft.com/en-us/graph/api/chatmessage-get):

    teams:///chats/{chatId}/messages/{messageId}
    teams:///teams/{teamId}/channels/{channelId}/messages/{messageId}
    teams:///teams/{teamId}/channels/{channelId}/messages/{rootId}/replies/{replyId}

The third is the one a search cannot mint. Graph addresses a reply in a channel thread *under* its
parent post, and the search projection carries no `replyToId`, so a channel hit that is really a
reply becomes the second shape, which Graph answers 404 to. `browse_channel` walks a channel post by
post and therefore knows each reply's parent, so it is the tool that mints this shape, and the
shape lives here rather than there.

The fourth and fifth address the meeting side:

    teams:///meetings/{joinWebUrl}
    teams:///transcripts/{meetingId}/{transcriptId}

A meeting is addressed by join URL because that is the only route Microsoft Graph gives a delegated
caller from chat to meeting. The chat collection's default projection carries
`onlineMeetingInfo.joinWebUrl`, and Graph's onlineMeetings lookup matches it byte for byte. No chat
id, topic, or date turns into one. It is a handle rather than a bare URL because Graph warns "don't
parse URLs": the tool takes something from a tool result, not something the model composed.

A transcript is addressed by the two ids its content path is built from, and not by the join URL
that reached it, because by then the resolve has already happened. A handle carrying the join URL
would make whoever reads a transcript repeat that lookup, spend a second request and a second
permission on it, and answer a 403 that could be about either of them.

The family name is the first segment. `teams:///meetings/{x}/transcripts/{y}` would make `{x}` a
join URL in one shape and a meeting id in another, and a parser cannot tell those two apart.
Distinct first segments it can tell apart, by construction.

Only Teams surfaces are handles. `mail:///` and `site:///` are not "not yet implemented": this
connector is scoped to Teams, and advertising schemes it cannot serve teaches models to ask for
things that always fail. A chat has no replies in Graph's addressing, so a
`teams:///chats/…/replies/…` is not a handle either.

Every segment is percent-encoded, because join URLs carry `:`, `/`, `?`, `&`, `%`, `#`, Teams ids
carry `:` and `@` (`19:...@thread.v2`), and handles must parse back cleanly. The parser rejects
half-encoded input: raw URL slashes would make multiple path segments, so hand-spelled handles come
back as "not a handle" rather than as truncated URLs that Graph ignores.

Permissions are per surface, and this module knows which surface addresses what, so the names
`CHAT_PERMISSION` and `CHANNEL_PERMISSION` live here. A permission in two files can be misspelled
in one, and Entra rejects unknown scopes at sign-in. So tools read these names from here rather
than repeat them, and declare their own `GRAPH_PERMISSIONS`, which is what their 403 is worded
from. A search names both, because it happens before anything knows which surface a hit will be on.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

# The two delegated permissions a Teams message is read under, one per surface. Here rather than in
# a tool file because `MessageHandle.permission` picks between them, and which surface a handle
# addresses is the whole of what decides it.
CHAT_PERMISSION = "Chat.Read"
CHANNEL_PERMISSION = "ChannelMessage.Read.All"


@dataclass(frozen=True, slots=True)
class MessageHandle:
    """Which message, in the one form this connector passes between tools."""

    message_id: str
    chat_id: str | None = None
    team_id: str | None = None
    channel_id: str | None = None
    reply_to_id: str | None = None

    @property
    def permission(self) -> str:
        """The one delegated Graph permission the message this handle addresses is read under."""
        return CHAT_PERMISSION if self.chat_id is not None else CHANNEL_PERMISSION

    @property
    def uri(self) -> str:
        """The handle as a string: what a search hit carries and a read echoes back."""
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
    """Meeting id: its join URL (the only route from chat to meeting)."""

    join_web_url: str

    @property
    def uri(self) -> str:
        return f"teams:///meetings/{_segment(self.join_web_url)}"


@dataclass(frozen=True, slots=True)
class TranscriptHandle:
    """Which transcript, by the two ids Graph's content path is built from.

    Graph's own `transcriptContentUrl` is not used, because the published samples are malformed
    (`…/transcripts/('…')/content`). The path is built from the ids instead, as Microsoft's
    reference shows.
    """

    meeting_id: str
    transcript_id: str

    @property
    def uri(self) -> str:
        return f"teams:///transcripts/{_segment(self.meeting_id)}/{_segment(self.transcript_id)}"


# Every shape, and only those. Ids are matched as "anything but a separator" because the spellers
# above percent-encode each one.
_CHAT_HANDLE = re.compile(r"\Ateams:///chats/([^/]+)/messages/([^/]+)\Z")
_CHANNEL_HANDLE = re.compile(r"\Ateams:///teams/([^/]+)/channels/([^/]+)/messages/([^/]+)\Z")
_REPLY_HANDLE = re.compile(
    r"\Ateams:///teams/([^/]+)/channels/([^/]+)/messages/([^/]+)/replies/([^/]+)\Z"
)
_MEETING_HANDLE = re.compile(r"\Ateams:///meetings/([^/]+)\Z")
_TRANSCRIPT_HANDLE = re.compile(r"\Ateams:///transcripts/([^/]+)/([^/]+)\Z")


def message_handle(uri: str) -> MessageHandle | None:
    """`uri` as a message handle, or None if it is not one this connector can read.

    None rather than an exception carrying advice: what to tell a caller about a malformed handle
    is the tool boundary's business, and each reader's advice names its own shapes and its own
    neighbouring tool.
    """
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
    """`uri` as a meeting handle, or None if it is not one."""
    match = _MEETING_HANDLE.match(uri)
    if match is None:
        return None
    join_web_url = unquote(match.group(1))
    return MeetingHandle(join_web_url) if join_web_url.strip() else None


def transcript_handle(uri: str) -> TranscriptHandle | None:
    """`uri` as a transcript handle, or None if it is not one."""
    match = _TRANSCRIPT_HANDLE.match(uri)
    if match is None:
        return None
    meeting_id, transcript_id = (unquote(part) for part in match.groups())
    if not meeting_id.strip() or not transcript_id.strip():
        return None
    return TranscriptHandle(meeting_id, transcript_id)


def meeting_uri_for(join_web_url: str | None) -> str | None:
    """Meeting handle for `join_web_url`, or None when Graph gave none.

    None is not a gap here: Graph giving a meeting chat no join URL is an outcome this module
    already knows how to have, so callers do not each decide it for themselves.
    """
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


def _segment(value: str) -> str:
    """Percent-encode value."""
    return quote(value, safe="")
