"""The `teams:///` handle grammar: every shape this connector mints, parser, and speller.

A handle is how one tool's answer becomes another tool's argument. Exactly one definition of each
shape must exist. Two modules spelling `teams:///meetings/…` would silently disagree. So the grammar
lives here, not in tool files. This is the only module that spells or parses these URIs (enforced
by tests/test_layering.py).

## The three shapes, and why they are three

Two of them are Graph's ways of addressing a Teams message
(https://learn.microsoft.com/en-us/graph/api/chatmessage-get):

    teams:///chats/{chatId}/messages/{messageId}
    teams:///teams/{teamId}/channels/{channelId}/messages/{messageId}

Graph has a third — a reply in a channel thread is addressed *under* the post it answers,
`…/messages/{rootId}/replies/{replyId}` — and it is deliberately not written yet. The search
projection carries no `replyToId`, so nothing this connector has can tell a reply from a root post;
a shape no tool can mint is a shape nothing has checked the spelling of, and it belongs with the
tool that walks a channel post by post and therefore knows each reply's parent. Which is also why a
channel hit that is really a reply gets the root-post shape above: it is the only true thing a
search can say about where that message lives.

The third shape: `teams:///meetings/{joinWebUrl}`. A meeting is addressed by join URL because that
is the only route Microsoft Graph gives a delegated caller from chat to meeting. The chat
collection's default projection carries `onlineMeetingInfo.joinWebUrl` and Graph's onlineMeetings
lookup matches it byte-for-byte. Nothing else—no chat id, topic, or date—turns into one.

A handle (not bare URL) because Graph warns "don't parse URLs". The tool takes something that came
from a tool result, not something the model composed.

The family name is the first segment. `teams:///meetings/{x}/transcripts/{y}` would make `{x}` a
join URL in one shape and a meeting id in another. A parser cannot tell them apart. Distinct first
segments can be, by construction.

Only Teams surfaces are handles. `mail:///` and `site:///` are not "not yet implemented"—this
connector is scoped to Teams. Advertising schemes it cannot serve teaches models to ask for things
that always fail. A chat has no replies in Graph's addressing, so a `teams:///chats/…/replies/…` is
not a handle either.

Every segment is percent-encoded because join URLs carry `:`, `/`, `?`, `&`, `%`, `#`, and Teams
ids carry `:` and `@` (`19:...@thread.v2`). Handles must parse back cleanly. The parser rejects
half-encoded input: raw URL slashes would make multiple path segments, so hand-spelled handles come
back as "not a handle" rather than truncated URLs that Graph ignores.

Permissions are per surface. This module knows which surface addresses what, so `CHAT_PERMISSION`
and `CHANNEL_PERMISSION` live here. A permission in two files can be misspelled in one. Entra
rejects unknown scopes at sign-in. So tools read these names from here rather than repeat them, and
declare their own `GRAPH_PERMISSIONS` (which is what their 403 is worded from). A search names both,
because it happens before anything knows which surface a hit will be on.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

# The two delegated permissions a Teams message surface is read under, one per surface. Here rather
# than in a tool file because they are facts about the surface a handle addresses rather than about
# any one request made against it.
CHAT_PERMISSION = "Chat.Read"
CHANNEL_PERMISSION = "ChannelMessage.Read.All"


@dataclass(frozen=True, slots=True)
class MessageHandle:
    """Which message, in the one form this connector passes between tools."""

    message_id: str
    chat_id: str | None = None
    team_id: str | None = None
    channel_id: str | None = None

    @property
    def uri(self) -> str:
        """The handle as a string — what a search hit carries and a read echoes back."""
        if self.chat_id is not None:
            return f"teams:///chats/{_segment(self.chat_id)}/messages/{_segment(self.message_id)}"
        assert self.team_id is not None and self.channel_id is not None, (
            "a handle addresses either a chat or a team channel"
        )
        channel = f"teams:///teams/{_segment(self.team_id)}/channels/{_segment(self.channel_id)}"
        return f"{channel}/messages/{_segment(self.message_id)}"


@dataclass(frozen=True, slots=True)
class MeetingHandle:
    """Meeting id: its join URL (the only route from chat to meeting)."""

    join_web_url: str

    @property
    def uri(self) -> str:
        return f"teams:///meetings/{_segment(self.join_web_url)}"


# Every shape, and only those. Ids are matched as "anything but a separator" because the spellers
# above percent-encode each one.
_CHAT_HANDLE = re.compile(r"\Ateams:///chats/([^/]+)/messages/([^/]+)\Z")
_CHANNEL_HANDLE = re.compile(r"\Ateams:///teams/([^/]+)/channels/([^/]+)/messages/([^/]+)\Z")
_MEETING_HANDLE = re.compile(r"\Ateams:///meetings/([^/]+)\Z")


def message_handle(uri: str) -> MessageHandle | None:
    """`uri` as a message handle, or None if it is not one this connector can address.

    None rather than an exception carrying advice: what to tell a caller about a malformed handle
    is the tool boundary's business, and each reader's advice names its own shapes and its own
    neighbouring tool.
    """
    chat = _CHAT_HANDLE.match(uri)
    if chat is not None:
        chat_id, message_id = (unquote(part) for part in chat.groups())
        return _message_handle(MessageHandle(message_id=message_id, chat_id=chat_id))
    channel = _CHANNEL_HANDLE.match(uri)
    if channel is not None:
        team_id, channel_id, message_id = (unquote(part) for part in channel.groups())
        return _message_handle(
            MessageHandle(message_id=message_id, team_id=team_id, channel_id=channel_id)
        )
    return None


def meeting_handle(uri: str) -> MeetingHandle | None:
    """Parse `uri` as a meeting handle or return None. None means malformed."""
    match = _MEETING_HANDLE.match(uri)
    if match is None:
        return None
    join_web_url = unquote(match.group(1))
    return MeetingHandle(join_web_url) if join_web_url.strip() else None


def meeting_uri_for(join_web_url: str | None) -> str | None:
    """Meeting handle for `join_web_url` or None when Graph gave none."""
    if join_web_url is None or not join_web_url.strip():
        return None
    return MeetingHandle(join_web_url).uri


def _message_handle(handle: MessageHandle) -> MessageHandle | None:
    """The handle, unless a segment decoded to nothing — `%20` is not an id."""
    ids = (handle.message_id, handle.chat_id, handle.team_id, handle.channel_id)
    if any(value is not None and not value.strip() for value in ids):
        return None
    return handle


def _segment(value: str) -> str:
    """Percent-encode value."""
    return quote(value, safe="")
