"""The `teams:///` grammar: every shape this connector mints, its parser and its speller.

A handle is how one tool's answer becomes another tool's argument — a chat becomes a meeting to ask
about. That only works while there is exactly *one* definition of each shape. Two modules that each
knew how to write `teams:///meetings/…` would be free to disagree, and the disagreement would not
look like a disagreement: it would look like a handle a tool produced and another tool answers 404
to. Which is why the grammar is not in any tool file, even the tool that mints the shape, and why
every family lives here rather than one per owner. The rule is enforced (`tests/test_layering.py`):
this is the only module that spells or parses one of these URIs.

## The shape, and why a meeting is addressed by a URL

    teams:///meetings/{joinWebUrl}

A meeting is addressed by its join URL because that is the only route Microsoft Graph gives a
delegated caller from Teams' conversation side to the meeting side: a meeting chat carries
`onlineMeetingInfo.joinWebUrl` in the chat collection's *default* projection, and Graph's
`onlineMeetings` lookup matches on that URL byte-for-byte against what it stored. Nothing turns a
chat id, a topic or a date into one.

A handle rather than a bare URL for the same reason the encoding below is not the caller's problem.
Graph warns that "users shouldn't rely on any information extracted from parsing the URL", so a
join URL is not an argument a model should be composing or re-spelling — wrapping it means the tool
that takes one takes something that came out of a tool result.

The family name is the first segment and stays the first segment as families are added: a
`teams:///meetings/{x}/transcripts/{y}` would make `{x}` a join URL in one shape and a meeting id
in another, and a parser cannot tell those apart. Distinct first segments can be, by construction.

Nothing else is a handle. `mail:///`, `site:///` and friends are not "not yet implemented" — this
connector is scoped to Teams, and advertising a scheme it cannot serve teaches a model to ask for
things that will always fail.

## Every segment is percent-encoded, and the join URL is why

A join URL carries `:`, `/`, `?`, `&`, `%` and `#` — and Teams ids, which later families are
addressed by, are full of `:` and `@` (`19:...@thread.v2`). A handle that has to be parsed back
apart cannot afford any of that, so every segment is encoded on the way out and `unquote`d on the
way in. The parser deliberately does not accept a half-encoded one: the slashes in a raw join URL
would make it several path segments, so a handle a model re-spelled by hand comes back as *not a
handle* rather than as a handle carrying a truncated URL that Graph would answer nothing for.

## Which permission a Teams surface is read under lives here too

Graph's permissions are per surface, and which surface something addresses is precisely what this
module knows — the chat surface is read under `Chat.Read`, and a refusal there can only be about
that name. Spelling a permission is therefore vocabulary rather than any one tool's business: a
name written out in two files is a name that can be misspelled in one of them, and Entra rejects an
authorize request carrying a scope it does not know, which fails sign-in for every user. So the
tools that read a chat name `CHAT_PERMISSION` from here rather than repeating the string, while
each still declares its own `GRAPH_PERMISSIONS` — that tuple is what its own 403 is worded from.
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
    """Which meeting, as the only thing a chat can say about one: its join URL."""

    join_web_url: str

    @property
    def uri(self) -> str:
        return f"teams:///meetings/{_segment(self.join_web_url)}"


# Every shape, and only that one. The id is matched as "anything but a separator" because the
# speller above percent-encodes it.
_MEETING_HANDLE = re.compile(r"\Ateams:///meetings/([^/]+)\Z")


def meeting_handle(uri: str) -> MeetingHandle | None:
    """`uri` as a meeting handle, or None if it is not one.

    None rather than an exception carrying advice: what to tell a caller about a malformed handle
    is the tool boundary's business, and each reader's advice names its own shapes and its own
    neighbouring tool.
    """
    match = _MEETING_HANDLE.match(uri)
    if match is None:
        return None
    join_web_url = unquote(match.group(1))
    return MeetingHandle(join_web_url) if join_web_url.strip() else None


def meeting_uri_for(join_web_url: str | None) -> str | None:
    """A meeting handle for `join_web_url`, or None when Graph gave none.

    What `list_chats` puts on a meeting chat, so that it can offer a route to the meeting without
    spelling a handle of its own. The None is the point: Graph giving a meeting chat no join URL is
    an outcome, and one this module already knows how to have — a caller left to decide for itself
    would be a second opinion about it.
    """
    if join_web_url is None or not join_web_url.strip():
        return None
    return MeetingHandle(join_web_url).uri


def _segment(value: str) -> str:
    return quote(value, safe="")
