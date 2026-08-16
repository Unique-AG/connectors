"""The `teams:///` handle grammar: every shape this connector mints, parser, and speller.

A handle is how one tool's answer becomes another tool's argument. Exactly one definition of each
shape must exist. Two modules spelling `teams:///meetings/…` would silently disagree. So the grammar
lives here, not in tool files. This is the only module that spells or parses these URIs (enforced
by tests/test_layering.py).

The shape: `teams:///meetings/{joinWebUrl}`. A meeting is addressed by join URL because that is the
only route Microsoft Graph gives a delegated caller from chat to meeting. The chat collection's
default projection carries `onlineMeetingInfo.joinWebUrl` and Graph's onlineMeetings lookup matches
it byte-for-byte. Nothing else—no chat id, topic, or date—turns into one.

A handle (not bare URL) because Graph warns "don't parse URLs". The tool takes something that came
from a tool result, not something the model composed.

The family name is the first segment. `teams:///meetings/{x}/transcripts/{y}` would make `{x}` a
join URL in one shape and a meeting id in another. A parser cannot tell them apart. Distinct first
segments can be, by construction.

Only Teams surfaces are handles. `mail:///` and `site:///` are not "not yet implemented"—this
connector is scoped to Teams. Advertising schemes it cannot serve teaches models to ask for things
that always fail.

Every segment is percent-encoded because join URLs carry `:`, `/`, `?`, `&`, `%`, `#`, and Teams
ids carry `:` and `@` (`19:...@thread.v2`). Handles must parse back cleanly. The parser rejects
half-encoded input: raw URL slashes would make multiple path segments, so hand-spelled handles come
back as "not a handle" rather than truncated URLs that Graph ignores.

Permissions are per surface. This module knows which surface addresses what, so `CHAT_PERMISSION`
lives here. A permission in two files can be misspelled in one. Entra rejects unknown scopes at
sign-in. So tools read `CHAT_PERMISSION` from here rather than repeat it, and declare their own
`GRAPH_PERMISSIONS` (which is what their 403 is worded from).
"""

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

# The delegated permission a Teams chat surface is read under. Here rather than in a tool file
# because it is a fact about the surface a handle addresses rather than about any one request made
# against it.
CHAT_PERMISSION = "Chat.Read"


@dataclass(frozen=True, slots=True)
class MeetingHandle:
    """Meeting id: its join URL (the only route from chat to meeting)."""

    join_web_url: str

    @property
    def uri(self) -> str:
        return f"teams:///meetings/{_segment(self.join_web_url)}"


_MEETING_HANDLE = re.compile(r"\Ateams:///meetings/([^/]+)\Z")


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


def _segment(value: str) -> str:
    """Percent-encode value."""
    return quote(value, safe="")
