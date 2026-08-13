"""The MCP tools, and the one seam every later tool inherits.

A tool is a function that (1) is handed the caller's Microsoft Graph token, (2) borrows the shared
HTTP transport to call Graph as that caller, and (3) reports a Graph failure as advice. There is
no registry, no base class and no decorator of our own: `register_tools` closes over the transport
`create_app` built, which is the whole of what FastMCP's plain-function tool signature would
otherwise need a process-wide service holder for.

Three conventions hold across every tool here, and a new one is expected to keep them, because a
model reads this surface as one thing:

* **A name is `verb_noun`** — `get_me`, `list_chats`, `list_teams`, `list_channels`,
  `browse_channel`, `search_messages`, `read_message`, `list_meeting_transcripts`,
  `read_transcript`, `list_meeting_recordings` — naming what the tool does and what it does
  it to. `whoami` was the one exception and is now `get_me`:
  the shell idiom made the odd tool out of the very tool a model calls first, and renaming a tool
  is a breaking change best spent before there are more of them. (Microsoft's own M365 connector
  arrived at `get_me` independently, which is one less name for a model to have to learn twice.)
* **One word for "there is more".** Every tool that answers with a list reports `truncated`, and
  says in its own description how to get the rest — a wider `limit` where there is no cursor, the
  `next_offset` where there is. Two words for one idea is how a model comes to guess.
* **A description teaches the traps, and the neighbours.** Each one says what it answers, when to
  reach for it rather than for another tool here, and what its answer does *not* mean.

The token comes from `EntraOBOToken`, FastMCP's own On-Behalf-Of dependency: it takes the Entra
token the caller presented (audience `api://{client_id}`, useless against Graph) and exchanges it
for a Graph one in the scopes named here. It is a dependency default, so it never appears in the
tool's input schema — the model cannot see it and cannot supply it. `_GraphToken` wraps it for
one reason: a dependency is resolved *outside* the tool body, so an exchange Entra refuses cannot
be explained by anything the body does.
"""

from datetime import date, datetime
from types import TracebackType
from typing import Annotated, cast, override
from uuid import UUID

import httpx
from fastmcp import FastMCP
from fastmcp.dependencies import Dependency
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import EntraOBOToken
from fastmcp.tools import Tool
from fastmcp.tools import tool as tool_metadata
from pydantic import Field

from office_mcp.features import (
    channels,
    chats,
    identity,
    message_read,
    message_search,
    recordings,
    transcripts,
)
from office_mcp.graph_client import graph_client_for
from office_mcp.server.errors import entra_token_errors, graph_tool_errors

# A Graph delegated permission, as a scope the On-Behalf-Of exchange can ask for. Graph accepts a
# bare permission name at the authorize endpoint too, but only because it is the default resource;
# the full form is unambiguous and is what FastMCP's own examples use.
_GRAPH_SCOPE_PREFIX = "https://graph.microsoft.com/"


def _scope(permission: str) -> str:
    return f"{_GRAPH_SCOPE_PREFIX}{permission}"


# What sign-in must ask Entra for, so that the On-Behalf-Of exchange has something to redeem: a
# Graph permission the user (or an administrator) never consented to cannot be obtained later, and
# the exchange fails with AADSTS65001 before the tool body runs. `_GraphToken` below turns that into
# advice, but a failure avoided at consent time beats one explained per call. `create_app`
# passes this to the auth provider — which is why it is the union of every tool's permission, and
# why it lives beside the tools that determine it.
GRAPH_SCOPES: tuple[str, ...] = tuple(
    # `dict.fromkeys` rather than a set: two tools sharing a permission must not make the scope
    # list a different string on every process start, or the consent screen and every cached
    # On-Behalf-Of token key change with it.
    dict.fromkeys(
        _scope(permission)
        for permission in (
            identity.GRAPH_PERMISSION,
            chats.GRAPH_PERMISSION,
            channels.TEAMS_PERMISSION,
            channels.CHANNELS_PERMISSION,
            channels.POSTS_PERMISSION,
            *message_search.GRAPH_PERMISSIONS,
            *message_read.GRAPH_PERMISSIONS,
            *transcripts.LISTING_PERMISSIONS,
            *recordings.LISTING_PERMISSIONS,
        )
    )
)


class _GraphToken(Dependency[str]):
    """`EntraOBOToken` for a tool's permissions, with the refusal explained in terms of them.

    The wrapping exists because of *where* the exchange happens. FastMCP resolves a dependency
    before it calls the tool, so a failure there never enters the tool body and never reaches the
    `graph_tool_errors` block inside it; FastMCP reports it as "Failed to resolve dependency
    'graph_token' for list_chats", which tells a model nothing it can act on. The one thing it
    does pass through untouched is a `FastMCPError` — so raising `ToolError` here, from the
    permissions this instance was built for, is what makes an unconsented permission as fixable
    before the Graph call as a 403 is after it.

    One instance covers one exchange, however many permissions that exchange asks for, because
    Entra redeems them together and refuses them together: a tool needing two gets one token or
    none. Naming all of them is therefore the same requirement as it is for a 403 — the refusal
    does not say which one was missing.

    The exchange itself is untouched: `__aenter__` delegates to FastMCP's dependency, which owns
    the credential cache, and `__aexit__` delegates so any cleanup it grows is not dropped.
    """

    def __init__(self, *permissions: str) -> None:
        assert permissions, "a token is exchanged for at least one permission"
        self._permissions: tuple[str, ...] = permissions
        # `EntraOBOToken` is annotated `-> str` (a lie for the type checker's benefit, so a tool
        # can annotate the token as the string it receives); the value is the dependency object.
        # Casting back to what it is has to go through `object` — the two types do not overlap.
        self._exchange: Dependency[str] = cast(
            "Dependency[str]",
            cast("object", EntraOBOToken([_scope(permission) for permission in permissions])),
        )

    @override
    async def __aenter__(self) -> str:
        with entra_token_errors(*self._permissions):
            return await self._exchange.__aenter__()

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._exchange.__aexit__(exc_type, exc_value, traceback)


def _graph_token(*permissions: str) -> str:
    """A `_GraphToken` typed as the token FastMCP will inject in its place.

    The same annotation `EntraOBOToken` uses, for the same reason: the tool body is handed a
    string and should say so, and the dependency object it never sees would otherwise have to be
    cast at every declaration site. The cast goes through `object` for the same reason it does
    above — a dependency is not a string, which is precisely why FastMCP replaces it with one.
    """
    return cast("str", cast("object", _GraphToken(*permissions)))


# The On-Behalf-Of dependency each tool declares as its token parameter's default, one per set of
# Graph permissions a tool calls under. Built here rather than inline because a call inside a
# parameter default rebuilds the descriptor on every registration and is a lint error in both of
# this repo's checkers. Sharing one instance is safe: FastMCP enters it per call and it holds
# nothing but its permissions.
_IDENTITY_TOKEN: str = _graph_token(identity.GRAPH_PERMISSION)
_CHATS_TOKEN: str = _graph_token(chats.GRAPH_PERMISSION)
_TEAMS_TOKEN: str = _graph_token(channels.TEAMS_PERMISSION)
_CHANNELS_TOKEN: str = _graph_token(channels.CHANNELS_PERMISSION)
_POSTS_TOKEN: str = _graph_token(channels.POSTS_PERMISSION)
_SEARCH_TOKEN: str = _graph_token(*message_search.GRAPH_PERMISSIONS)
_READ_TOKEN: str = _graph_token(*message_read.GRAPH_PERMISSIONS)
_TRANSCRIPT_LIST_TOKEN: str = _graph_token(*transcripts.LISTING_PERMISSIONS)
_TRANSCRIPT_TOKEN: str = _graph_token(transcripts.TRANSCRIPT_PERMISSION)
_RECORDING_LIST_TOKEN: str = _graph_token(*recordings.LISTING_PERMISSIONS)

_GET_ME = """\
Return the signed-in Microsoft 365 user's own profile: `user_id`, `display_name`, `email`, \
`user_principal_name` and `job_title`.

Call this before anything that turns on who "I", "me" or "my" is: filtering a message search to \
the signed-in user, deciding which participant of a chat is them, or addressing them by name. It \
is one cheap request and its answer is stable for the session. Its `user_id` is the value \
search_messages matches `mentions` on — a name will not work there — and the one to compare a \
recording's `organizer_user_id` against; `email` is what a chat member from list_chats is matched \
by, because that list carries no ids at all.

`email` is the canonical primary SMTP address (Microsoft's `mail`) and the right value to match a \
sender or recipient against — but it is null for guest and unlicensed accounts, and \
`user_principal_name` (Microsoft's `userPrincipalName`) is then the best available identifier. Do \
not treat the two as interchangeable when both are present: a tenant can issue a \
user_principal_name on a different domain from the email address, so matching message addresses \
against it can silently return nothing. Compare `user_id` — the immutable directory object id — \
against the `user_id` of a message's sender or of a mention; compare `email` against an address, \
which is all a chat's member list gives you to match on.\
"""

_LIST_CHATS = f"""\
List the Microsoft Teams chats the signed-in user is a member of — one-to-one, group and meeting \
chats — most recently active first, with each chat's id, type, topic, last-message time and (for \
unnamed chats) its members.

Reach for this to see which conversations are live, who is in them, and when each was last posted \
in — never for what was said in them: no message text is returned here, and search_messages is the \
route to any. The other use is naming: a `chat_id` here is the same id search_messages puts \
on every chat message it finds, so this list is how a found message gets a topic and a set of \
participants. It is not an argument to anything — no tool here takes a chat id, and a search \
cannot be narrowed to one chat. This returns chats only: Teams channels live inside teams, are \
listed by list_teams and list_channels, and are read by browse_channel.

**This is also how a meeting is found.** A `meeting` chat is the conversation attached to a Teams \
meeting, its `topic` is the meeting's subject, and it carries `meeting_uri` — the handle \
list_meeting_transcripts and list_meeting_recordings both take. So "what was decided in the \
pricing call last Tuesday" and "was that call recorded" both start here: find the meeting chat by \
topic and recency, then follow its `meeting_uri`. There is no \
separate meeting-search tool because this list already answers which meeting, and no Microsoft \
calendar permission is involved. `meeting_uri` is null on every non-meeting chat, and null on a \
meeting chat Microsoft returned no join URL for — that meeting's transcript is then unreachable \
here, and no other tool or argument will reach it.

Ordering and `last_message_at` both come from the last message actually sent in the chat, which is \
the only notion of recency Microsoft Graph will sort this collection by. The chat property that \
looks like activity — Graph's `lastUpdatedDateTime` — is not returned here on purpose: Graph \
defines it as when the chat was renamed or its membership changed, so a chat nobody has posted in \
for a year can carry yesterday's timestamp. `last_message_at` is null for a chat with no messages.

`members` is returned only for chats whose `topic` is null, because those chats have no other \
name; Graph caps that list at {chats.MEMBERS_PER_CHAT} members per chat and sends no member \
total, so `members_may_be_incomplete` says when a list came back full to that cap — people may \
be missing from it, and Graph will not say whether they are. Set `include_member_emails` when \
two members share a display name.

There is no pagination. `limit` is a window on the most recent chats and `truncated` says whether \
the user has more than fit in it — widen `limit` (up to {chats.MAX_CHATS}, Graph's own maximum \
for this collection) rather than looking for a cursor. The signed-in user's own notes-to-self \
chat is usually the oneOnOne chat whose only member is them (call get_me to know who that is; a \
member is matched by display name or, with `include_member_emails`, by email — this list carries \
no user ids).\
"""

_LIST_TEAMS = f"""\
List the Microsoft Teams teams the signed-in user is a member of, with each team's id, name, \
description and archived flag.

This is the first step into the channel side of Teams, which list_chats does not cover at all: a \
`team_id` here is what list_channels takes, and browsing what was posted in a channel starts from \
that. It answers "which teams am I in" and nothing more — no channels, no members, no messages, \
and no activity date, because Microsoft Graph populates none of those on this collection whether \
or not they are asked for.

`is_archived` marks a team that is read-only in Teams, which usually means finished; together with \
`description` it is what tells apart two teams sharing a display name. Teams that merely host a \
shared channel the user belongs to are not listed — Microsoft returns only teams the user is a \
member of.

There is no pagination and no ordering: Microsoft Graph accepts no page size on this collection, \
and applies no order to it, so `limit` is a window over whatever order it answered in and \
`truncated` says the user is in more teams than fit. Widen `limit` (up to {channels.MAX_LISTED}) \
rather than looking for a cursor.\
"""

_LIST_CHANNELS = f"""\
List the channels of one Microsoft Teams team, identified by the `team_id` list_teams returned: \
each channel's id, name, description, membership type and creation date.

Call this to find the channel to browse, then pass `team_id` and `channel_id` together to \
browse_channel — a channel id alone addresses nothing. Channel names are unique only inside their \
own team (every team has a `General`), which is why the pair is always needed. No message content \
is returned here.

The list is already trimmed to what the signed-in user may see: Microsoft omits private and shared \
channels they are not a member of, so an absent channel is not evidence that the team has no such \
channel. `membership_type` says which kind each one is — `standard`, `private` or `shared`.

There is no pagination and no ordering, for the same reason as list_teams: Microsoft accepts no \
page size on this collection either. `truncated` says the team has more channels than this `limit` \
holds; widen it (up to {channels.MAX_LISTED}).\
"""

_BROWSE_CHANNEL = f"""\
Read what was posted in one Microsoft Teams channel: its posts with their full text, each followed \
by the replies to it. Takes the `team_id` and `channel_id` list_teams and list_channels returned.

This is the one thing the other message tools cannot do — walk a single channel in order. \
search_messages finds messages by keyword across every chat and channel at once but cannot be \
scoped to one channel, and read_message reads a single message you already have a handle for. \
Reach for this when the question is "what is going on in this channel" rather than "where was this \
mentioned". Do not call it for channel after channel: Microsoft rate-limits reads of a given \
channel to about one request a second for this whole connector across the tenant, so a sweep is \
slow for you and harmful to everyone else on it — search_messages covers every channel in one \
request. This call spends exactly one request of that budget: it reads the single page Microsoft \
answers with and never pages deeper, so `limit` is the whole window and widening `limit` — not \
calling again — is how to see more.

**The order is not what it looks like.** Microsoft sorts this collection by the last modified time \
of the entire reply chain, so a two-year-old post returns to the front the moment somebody replies \
to it. The first message here is the most recently *active* thread, not the most recent post. Read \
`created_at` before saying when anything was written, never the position in this list, and do not \
report the top of the list as "the latest news in the channel".

It cannot be date-filtered, and this is Microsoft's limit rather than a missing parameter: this \
collection accepts no filter and no sort at all. To bound by date use search_messages with \
`sent_after`/`sent_before`, which the search index applies and which covers channels. For the same \
reason, paging deeper is not a way to reach older posts — there is no cursor, and `truncated` is \
answered by a wider `limit` (up to {channels.MAX_POSTS}, Microsoft's own maximum) or by searching.

Replies come with their posts: up to {channels.MAX_REPLIES_PER_POST} of the newest per post, \
oldest first, each carrying the post it answers in `reply_to_id`. `truncated` is also set when a \
thread had more replies than that, and those older replies are out of reach rather than one call \
away — Microsoft's cursor into a thread is a request per post against the same one-a-second \
budget, so it is not followed and browsing again returns the same newest replies. Every message is \
complete — the same fields, and the same plain text normalised out of Teams' HTML, that \
read_message returns — so a message here needs no second call to read it. Its `uri` is a handle \
for quoting or re-reading it, and for a reply it is the only handle that exists: Microsoft \
addresses a reply under its parent post, which a search result cannot express. That is also the \
limit of what this tool can rescue: when a search hit is a reply older than the window above, \
there is no route to its full text anywhere in this connector — report the search snippet, say so, \
and do not browse again for it.

System messages are dropped — somebody joining, a call ending, a channel being renamed — because \
Microsoft gives them no author and no text. That is why a page can hold fewer posts than `limit`, \
and it is not evidence that the channel is quiet.\
"""

_SEARCH_MESSAGES = f"""\
Search the Microsoft Teams messages the signed-in user can see — every one-to-one chat, group \
chat, meeting chat and channel they belong to — by keywords, sender, mentions, date, attachments \
and read state. Messages from ANY participant match, not only the user's own; call get_me if you \
need to know who the user is. It is the only tool here that searches: it finds messages anywhere, \
read_message reads one of them in full, and browse_channel is what walks a single channel when the \
question is about that channel rather than about a keyword.

A result is metadata plus a snippet, by necessity. Microsoft's search index answers with a reduced \
view of a message that contains no message body at all, so `summary` — Microsoft's own excerpt, \
truncated with `...` where it was cut — is the only text here. Every hit carries a `uri` handle \
identifying that exact message; pass it to read_message for the real text, the attachments and the \
mentions. Never present `summary` as the whole message, and never conclude from it that the \
message does not say more.

There is no result total, and this is not an omission: Microsoft Graph reports a per-page count \
rather than a match count for Teams messages, so a total would be a fabrication. `truncated` says \
there is more — as it does on every list-shaped tool here — and here the way to get it is to pass \
`next_offset` back as `offset`. A page can hold fewer than `size` messages: offsets index Graph's \
own results, and system messages ("Ada joined the chat") are dropped from ours because Graph gives \
them neither an author nor any text.

The search covers every chat and channel the user belongs to and cannot be narrowed to one of \
them — Microsoft's index offers no such scope, so there is no chat or channel parameter and a \
`chat_id` from list_chats is not one. Narrow with `sender`, dates or more words instead, and read \
`chat_id` (or `team_id`/`channel_id`) on each hit to see where it came from.

Results cannot be sorted: Graph refuses sort options on a message search. Its documented default \
for message results is newest first and relevance can be mixed in, so compare `created_at` \
whenever order matters to the answer.

At least one criterion is required and all criteria given are ANDed. `query` is matched as plain \
words and every word must appear, anywhere in the message and in any order — the words do not have \
to be next to each other. To require that they are, quote them yourself: `"release notes"` matches \
only where those two words are adjacent. Search operators typed into `query` are searched for \
literally, so put a sender in `sender`, a date in `sent_after`/`sent_before`, and so on. Those two \
dates are inclusive whole days and are \
applied by the index itself, so a date-bounded search still costs one request and still covers \
channels. `recipient` is honoured by Microsoft only for one-to-one chats and will hide group and \
channel matches, so prefer `sender`. Channel matches need the delegated \
{message_search.CHANNEL_PERMISSION} permission, which this connector requires at sign-in rather \
than degrading to chats-only search without saying so.\
"""

# What the tool says when it is called with nothing to look for. Graph would answer such a request
# with an arbitrary slice of everything the user can read, which reads like a real result set and
# is the one failure mode a model cannot detect from the response.
_NO_CRITERIA = (
    "search_messages needs at least one of "
    + ", ".join(message_search.CRITERIA)
    + ". Searching with none of them would return an arbitrary sample of every message the user "
    + "can see, not an answer. Add the keywords, person or date range the question is about."
)

_READ_MESSAGE = """\
Read one Microsoft Teams message in full, from the `uri` handle a search_messages result carries: \
the whole message text, who sent it, who was @-mentioned, what was attached, and whether it has \
been edited or deleted.

This is the other half of search_messages, and the only route to the text of a message a search \
found. Microsoft's search index answers with a reduced view of a message that contains no body at \
all, so a search result carries only Microsoft's `summary` snippet. Read the message here whenever \
the answer depends on what somebody actually said rather than on the fact that a matching message \
exists — and never present a snippet as the message. A message browse_channel returned needs no \
read: that tool answers with the whole message already.

`uri` takes a handle this connector produced, in one of exactly three shapes:
  teams:///chats/{chat_id}/messages/{message_id}
  teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}
  teams:///teams/{team_id}/channels/{channel_id}/messages/{root_id}/replies/{reply_id}
Nothing else is readable here. No handle of this connector's names mail, a calendar event, a file \
or a SharePoint page, and nothing turns a person's name or a chat topic into one — pass the `uri` \
from a tool result verbatim. A meeting transcript is the one other thing this connector reads and \
it has its own reader: a `teams:///transcripts/...` handle goes to read_transcript, not here. The \
third shape above is the one only browse_channel emits: Microsoft addresses a reply in a channel \
thread under the post it answers, and a search result does not say which post that is.

`text` is plain text, normalised from Teams' own HTML: a mention reads as `@Name`, a list item as \
`- `, an attachment as `[attachment: name]`, an inline image as `[image]` and a card as `[card]`. \
`mentions` and `attachments` say who and what those refer to. Nothing else is summarised or \
abridged — a message that happens to contain JSON, a config fragment or code is somebody's own \
words and comes back verbatim, and `[card]` appears only where `attachments` names a card.

Two messages have no text and must not be reported as empty ones. A deleted message returns \
`deleted_at` and no text: say it was deleted. A system event message — somebody joining, a call \
ending, a chat being renamed — has no author and no text anywhere in Microsoft Graph, because the \
sentence Teams displays is written by the Teams client and never sent. For those, `event` names \
what happened, and inventing the wording of one is a fabrication.\
"""

# What the tool says when `uri` is not a handle at all. This is the failure that is *our* fault to
# explain — the two below are Microsoft's answers — so it is the one that shows the shapes.
_BAD_HANDLE = (
    "read_message takes a `uri` handle that search_messages or browse_channel produced, and this "
    + "is not one. A readable handle has one of exactly three shapes:\n"
    + "  teams:///chats/{chat_id}/messages/{message_id}\n"
    + "  teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}\n"
    + "  teams:///teams/{team_id}/channels/{channel_id}/messages/{root_id}/replies/{reply_id}\n"
    + "with the ids percent-encoded, e.g. "
    + "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000. Copy the `uri` of a tool "
    + "result rather than assembling one. This reader serves Teams messages only: no mail, files "
    + "or sites are addressable in this connector at all, and a meeting transcript handle "
    + "(teams:///transcripts/...) belongs to read_transcript. Retrying this value will fail "
    + "identically."
)

# Graph's 404 on a well-formed handle, which is a different failure from a malformed one and must
# not be reported as the message never having existed.
_UNREADABLE = (
    "Microsoft 365 would not return this message. The handle is well formed, so this is not a bad "
    + "argument — and it is not evidence that the message does not exist: Graph answers 'deleted', "
    + "'never existed' and 'the signed-in user may not see it' with the same 404, and does not say "
    + "which of them it meant. Report that the message could not be read, never that it was never "
    + "written. Retrying will not help and this connector has no other route to the text. One "
    + "well-formed handle always fails this way: a reply in a channel thread is addressed under "
    + "the post it answers, and a search result does not identify that post — so a search hit that "
    + "is a reply cannot be read from its own handle. browse_channel is the only tool that emits a "
    + "reply's own handle, and it reaches the newest "
    + f"{channels.MAX_REPLIES_PER_POST} replies of each post on the channel's first page and no "
    + "further: it follows neither Microsoft's cursor into an older part of a thread nor the one "
    + "into older posts, because a given channel allows this whole connector about one request a "
    + "second across the tenant. So browse that channel once; if the reply is not in what comes "
    + "back there is no route to its full text, and a second browse returns the same window. "
    + "Report the search snippet with its sender and date, say the full text could not be "
    + "retrieved, and stop looking."
)

_LIST_MEETING_TRANSCRIPTS = f"""\
Find out whether a Teams meeting was transcribed, and get a handle for each transcript. Takes the \
`meeting_uri` that list_chats reports on a meeting chat.

This is the first half of reading a meeting: this tool says what exists, read_transcript returns \
what was said. Two calls rather than one because a transcript is large and because a recurring \
meeting is a single meeting to Microsoft — every occurrence's transcript lands in the same \
collection, distinguished only by when transcription started — so which one to read is a decision, \
not a default. Scope to one occurrence with `started_after`/`started_before` when \
`meeting_type` comes back `recurring`; a one-off meeting has a single transcript and needs \
neither. Both bounds take a date (`2026-08-11`, meaning that whole UTC day) or a timestamp, with \
or without a timezone offset — one without is read as UTC, so pass the offset when you are working \
from a local time.

**Read `status` before anything else. It has five values and they mean five different actions:**
- `available` — transcripts are listed, newest first; read one with read_transcript.
- `not_ready` — nothing has landed for the window you asked about and something still might: that \
window has only just closed, or you asked for no window and the meeting has not ended or ended \
recently. Wait and call again later. This is NOT "there is no transcript", and reporting it as one \
is wrong: Microsoft publishes no availability SLA, so this tool infers it from how recently the \
window (or the meeting) ended and errs towards telling you to wait. An occurrence window that is \
already well past never answers this — a series whose end date is in the future does not make a \
last-month occurrence "still processing".
- `not_transcribed` — the window you asked about is over and nothing is there: it was not recorded \
or not transcribed. Retrying will not help. Say the meeting has no transcript rather than that the \
meeting did not happen. (One other cause is indistinguishable: Microsoft stops serving a meeting's \
transcripts once the meeting expires, roughly 60 days after a one-off.)
- `scan_incomplete` — this meeting has more transcripts than one call looks through \
({transcripts.MAX_ARTIFACT_SCAN}) and none of the ones looked at are in your window, so whether \
one exists there is not known. This is the one answer that claims nothing: narrow \
`started_after`/`started_before` to the occurrence you mean and ask again. Never report it as \
"there is no transcript".
- `meeting_not_found` — Microsoft matched the join URL in the handle to no meeting this user can \
see. Not an error, and not proof the meeting is gone. Do not retry and do not rebuild the handle.

This tool answers about transcripts only. Whether the meeting was RECORDED is a separate question \
with a separate answer — list_meeting_recordings, which takes the same `meeting_uri` — because \
Microsoft gates the two independently: the tenant setting below blocks transcripts and leaves \
recordings alone, so when this call is refused that one may still answer. No video is returned or \
reachable anywhere in this connector; a transcript is the better artifact for a question about a \
meeting anyway, being text with who said what and when.

Two things can refuse this call outright, and both are somebody's decision rather than a bug. \
Reading transcripts over Microsoft Graph is an organisation-wide Teams setting that is OFF by \
default and that no application can switch on; when it is off, the error says so and names the \
administrator who can change it. Separately, Microsoft documents transcript access under \
{transcripts.TRANSCRIPT_PERMISSION} without stating that meeting participants get it, so a \
participant may be refused where the meeting's organiser would succeed.\
"""

_READ_TRANSCRIPT = f"""\
Read what was said in a Teams meeting: the transcript as speaker-attributed, timestamped turns. \
Takes the `uri` of a transcript that list_meeting_transcripts returned.

This is the payoff of the whole meeting path, and it returns the words themselves rather than a \
link to them — who spoke, in order, with the offset into the meeting at which they spoke. Quote it \
as you would quote a message: it is what people actually said, verbatim, and Microsoft's \
speech-to-text is not perfect, so an odd word is likelier a mis-transcription than a real one.

`uri` takes a handle this connector produced, in exactly one shape:
  teams:///transcripts/{{meeting_id}}/{{transcript_id}}
Nothing else is readable here, and nothing turns a meeting's name, its date, its chat or its \
`meeting_uri` into one — call list_meeting_transcripts and pass its `uri` verbatim. read_message \
is the reader for a Teams message and takes a different handle; neither tool accepts the other's.

`start_seconds` and `end_seconds` are offsets in seconds from the moment transcription began, not \
wall-clock times and not offsets from the start of the meeting; add them to the transcript's \
`started_at` from list_meeting_transcripts if an absolute time is needed. They can be negative, \
which Microsoft defines as transcription having started after the conversation did.

`speaker_attribution` is false when the organisation has turned speaker names off. The words and \
timings still come back and every `speaker` is null: do not infer who spoke from the content, and \
say the transcript is unattributed if the answer turns on who said something. **A `speaker` filter \
matches nothing at all on such a transcript** — there is no name on any turn for it to match — so \
read an empty answer next to this flag before reporting that the person never spoke, and drop the \
filter to see the turns themselves.

`from_seconds`/`to_seconds` and `speaker` narrow what comes back, and everything else is counted \
over what they left: `truncated` and `next_offset` page through the MATCHING turns rather than \
through the meeting. The time bounds are inclusive and match by overlap, so a turn already under \
way at `from_seconds` is kept whole instead of being cut at it; `speaker` matches any part of the \
name Teams shows, ignoring case, because a display name is not something to spell from memory. \
Filtering does not make the call cheaper — the whole transcript is fetched and parsed either \
way — it makes the answer smaller.

A long meeting is more turns than fit in one answer. `truncated` says there are more and \
`next_offset` is where to continue — the same convention every list-shaped tool here uses. Each \
call re-fetches the whole transcript from Microsoft, so a wider `limit` (up to \
{transcripts.MAX_TURNS}) costs less than paging through it, and a truncated page must never be \
summarised as the whole meeting.\
"""

_LIST_MEETING_RECORDINGS = f"""\
Find out whether a Teams meeting was recorded, how long the recording runs, and whether the \
signed-in user is allowed to download it. Takes the same `meeting_uri` that list_chats reports on \
a meeting chat.

This is the only tool here that answers "was Tuesday's call recorded" — and it answers it with \
metadata, never with video. **No video is returned or reachable anywhere in this connector.** A \
Teams meeting can run 30 hours, Microsoft serves a recording as one MP4 byte stream, and a model \
cannot watch video, so returning it would be neither possible nor useful. What comes back is what \
can actually be acted on: that a recording exists, when it started and stopped, how long it runs, \
who may download it, and which transcript is the same call.

**`content_access` is the "can I get at it" answer, and it is not about this connector.** \
Microsoft documents recording download as ORGANISER-ONLY under delegated access — "Meeting \
participants don't have permission to download meeting recordings" — unless a tenant administrator \
has unblocked participants. So `organizer_only` means the recording is real and its video is out \
of this user's reach: say it exists, say who has it (`organizer_user_id`, comparable with get_me's \
`user_id`), and offer the transcript instead. \
Never report an `organizer_only` recording as a missing one. \
`you_are_the_organizer` means Microsoft permits this user to download it in Teams or SharePoint — \
not here, and an administrator can still have blocked recording downloads tenant-wide.

**The readable artifact is the transcript, and `content_correlation_id` is the exact link to it.** \
For any question about what was said, call list_meeting_transcripts for the same meeting and read \
the transcript whose `content_correlation_id` matches this recording's: that is Microsoft's own \
identifier for "these two are the same call". Reach for this tool when the question is about the \
recording itself — was there one, how long, who has it — or when list_meeting_transcripts has \
already said `not_transcribed` and the remaining question is whether anything was captured at all.

**Read `status` before anything else. It has five values and they mean five different actions:**
- `available` — recordings are listed, newest first, with durations and access.
- `not_ready` — nothing has landed for the window you asked about and something still might: that \
window has only just closed, or you asked for no window and the meeting has not ended or ended \
recently. Wait and call again later. This is NOT "the call was not recorded", and reporting it as \
one is wrong: Microsoft publishes no availability SLA for a recording, so this tool infers it from \
how recently the window (or the meeting) ended and errs towards telling you to wait. An occurrence \
window that is already well past never answers this.
- `not_recorded` — the window you asked about is over and nothing is there: nobody recorded it. \
Retrying will not help. (One other cause is indistinguishable: Microsoft stops serving a meeting's \
artifacts once the meeting expires, roughly 60 days after a one-off.)
- `scan_incomplete` — this meeting has more recordings than one call looks through \
({transcripts.MAX_ARTIFACT_SCAN}) and none of the ones looked at are in your window, so whether \
one exists there is not known. This is the one answer that claims nothing: narrow \
`started_after`/`started_before` to the occurrence you mean and ask again. Never report it as "the \
call was not recorded".
- `meeting_not_found` — Microsoft matched the join URL in the handle to no meeting this user can \
see. Not an error, and not proof the meeting is gone. Do not retry and do not rebuild the handle.

`duration_seconds` is computed from the recording's own start and end, because Microsoft publishes \
no duration property at all; it is null where either timestamp is missing, and it is the \
recording's length rather than the meeting's. Scope a recurring series to one occurrence with \
`started_after`/`started_before`, exactly as with list_meeting_transcripts — a whole series is one \
meeting to Microsoft, so every occurrence's recording is in the same collection. Both bounds take \
a date (`2026-08-11`, meaning that whole UTC day) or a timestamp with or without an offset; one \
without is read as UTC.

Unlike transcripts, recordings are NOT behind the tenant-wide Teams switch for Graph transcript \
access, so this tool can succeed in an organisation where list_meeting_transcripts is refused \
outright. Reading recordings does need its own admin-consented permission \
({recordings.RECORDING_PERMISSION}); when Microsoft refuses this call the error names it.\
"""

# What each reader says when its `uri` is not one of its own handles. Separate texts because the two
# handle families are separate: pointing a caller at the wrong tool is the failure these prevent.


def _not_a_meeting_handle(tool: str) -> str:
    """The refusal for a `meeting_uri` that is not a meeting handle, named for the tool that got it.

    One text with the tool's name substituted rather than one per tool: both meeting listers take
    the same handle from the same place, so the advice differs in exactly one word and two copies of
    it would be free to drift.
    """
    return (
        f"{tool} takes the `meeting_uri` that list_chats reports on a meeting chat, "
        + "and this is not one. A meeting handle has exactly one shape:\n"
        + "  teams:///meetings/{join_web_url}\n"
        + "with the join URL percent-encoded. It cannot be assembled — Microsoft addresses a "
        + "meeting by the join URL of the Teams meeting itself, which only Microsoft can supply — "
        + "so call list_chats, find the `meeting` chat for the meeting in question, and pass its "
        + "`meeting_uri` verbatim. A chat id, a chat topic, a Teams web link and a "
        + "`teams:///transcripts/...` handle are none of them a meeting handle. Retrying this "
        + "value will fail identically."
    )


_NOT_A_TRANSCRIPT_HANDLE = (
    "read_transcript takes the `uri` of a transcript that list_meeting_transcripts returned, and "
    + "this is not one. A transcript handle has exactly one shape:\n"
    + "  teams:///transcripts/{meeting_id}/{transcript_id}\n"
    + "with both ids percent-encoded. Call list_meeting_transcripts with a meeting chat's "
    + "`meeting_uri` and pass the `uri` of the transcript you want, verbatim. A `meeting_uri` is "
    + "not a transcript handle — one meeting can have many transcripts — and neither is a Teams "
    + "message handle. Retrying this value will fail identically."
)

# The two things `read_transcript`'s filters can be asked that a signature cannot refuse. A schema
# bounds one argument at a time, so neither a window whose ends are the wrong way round nor a filter
# value that is nothing but spaces is expressible in it — and both would otherwise be answered with
# an empty page, which is the one failure a model reads as a real answer.
_INVERTED_TIME_WINDOW = (
    "read_transcript was given a `from_seconds` later than its `to_seconds`, which selects no part "
    + "of the meeting: no turn can both end after the one and start before the other, so this "
    + "would come back empty and read like a silent meeting. Both are offsets in seconds from the "
    + "moment transcription began, counting upwards, so the earlier moment is the smaller number — "
    + "swap them if they were written the wrong way round, or drop one to leave that end open."
)

_BLANK_SPEAKER = (
    "read_transcript was given a blank `speaker`. A blank filter is not the same as no filter, and "
    + "it is not treated as one: omit `speaker` entirely to read every turn, or pass any part of "
    + "the name Teams shows for the person — matching ignores case and matches anywhere in the "
    + "display name, so `ada` finds `Ada Lovelace`. Note that a transcript whose "
    + "`speaker_attribution` is false carries no names at all, and any `speaker` filter matches "
    + "nothing on it."
)

# Graph's 404 on a well-formed transcript handle. Distinct advice from the message reader's, because
# the causes are different: a transcript is not deleted by a user, it ages out with its meeting.
_TRANSCRIPT_UNREADABLE = (
    "Microsoft 365 would not return this transcript. The handle is well formed, so this is not a "
    + "bad argument. The likeliest cause is age: Microsoft stops serving a meeting's transcripts "
    + "once the meeting expires, about 60 days after a one-off meeting, and it answers that "
    + "identically to a transcript that was removed or that this user may not see. Call "
    + "list_meeting_transcripts for the meeting again to see what it still has; if the transcript "
    + "is no longer listed there, it is out of reach and retrying will not bring it back."
)

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}


def register_tools(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this server's tools against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tools
    below borrow it per call and never own it. `create_app` closes it on shutdown.
    """

    @mcp.tool(name="get_me", title="Get My Profile", description=_GET_ME, annotations=_READ_ONLY)
    async def get_me(graph_token: str = _IDENTITY_TOKEN) -> identity.SignedInUser:
        with graph_tool_errors(identity.GRAPH_PERMISSION):
            return await identity.get_signed_in_user(graph_client_for(transport, graph_token))

    @mcp.tool(
        name="list_chats",
        title="List My Teams Chats",
        description=_LIST_CHATS,
        annotations=_READ_ONLY,
    )
    async def list_chats(
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=chats.MAX_CHATS,
                description=(
                    "How many chats to return, most recently active first. Default 25, maximum "
                    + f"{chats.MAX_CHATS} — Microsoft Graph refuses a larger page on this "
                    + "collection."
                ),
            ),
        ] = 25,
        include_member_emails: Annotated[
            bool,
            Field(
                description=(
                    "Include each listed member's email address. Off by default: it is only "
                    + "needed to tell apart two members with the same display name."
                )
            ),
        ] = False,
        graph_token: str = _CHATS_TOKEN,
    ) -> chats.ChatList:
        with graph_tool_errors(chats.GRAPH_PERMISSION):
            return await chats.list_recent_chats(
                graph_client_for(transport, graph_token),
                limit=limit,
                include_member_emails=include_member_emails,
            )

    @mcp.tool(
        name="list_teams",
        title="List My Teams",
        description=_LIST_TEAMS,
        annotations=_READ_ONLY,
    )
    async def list_teams(
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=channels.MAX_LISTED,
                description=(
                    "How many teams to return. Default 50, maximum "
                    + f"{channels.MAX_LISTED} — Microsoft Graph applies no page size to this "
                    + "collection, so this is a window this connector applies while paging it."
                ),
            ),
        ] = 50,
        graph_token: str = _TEAMS_TOKEN,
    ) -> channels.TeamList:
        with graph_tool_errors(channels.TEAMS_PERMISSION):
            return await channels.list_teams(graph_client_for(transport, graph_token), limit=limit)

    @mcp.tool(
        name="list_channels",
        title="List a Team's Channels",
        description=_LIST_CHANNELS,
        annotations=_READ_ONLY,
    )
    async def list_channels(
        team_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The team whose channels to list, exactly as list_teams reported its "
                    + "`team_id`. Opaque — a team's name is not one, and one cannot be "
                    + "constructed."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=channels.MAX_LISTED,
                description=(
                    "How many channels to return. Default 50, maximum "
                    + f"{channels.MAX_LISTED} — as with list_teams, Microsoft Graph applies no "
                    + "page size here and this is the window applied while paging."
                ),
            ),
        ] = 50,
        graph_token: str = _CHANNELS_TOKEN,
    ) -> channels.ChannelList:
        with graph_tool_errors(channels.CHANNELS_PERMISSION):
            return await channels.list_channels(
                graph_client_for(transport, graph_token), team_id=team_id, limit=limit
            )

    @mcp.tool(
        name="browse_channel",
        title="Browse a Teams Channel",
        description=_BROWSE_CHANNEL,
        annotations=_READ_ONLY,
    )
    async def browse_channel(
        team_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The team the channel belongs to, exactly as list_teams reported its "
                    + "`team_id`. A channel id alone does not address a channel."
                ),
            ),
        ],
        channel_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The channel to read, exactly as list_channels reported its `channel_id` (or "
                    + "as search_messages reported `channel_id` on a channel message). Opaque — a "
                    + "channel's name is not one."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=channels.MAX_POSTS,
                description=(
                    "How many posts to return, each with its replies. Default 20 and maximum "
                    + f"{channels.MAX_POSTS} — both Microsoft Graph's own, for this collection. "
                    + "One call is one request against the channel and this is the whole of its "
                    + "window: widen it to see more rather than calling again. System messages are "
                    + "dropped after Graph counts them, so a page can hold fewer posts than this."
                ),
            ),
        ] = 20,
        graph_token: str = _POSTS_TOKEN,
    ) -> channels.ChannelPosts:
        with graph_tool_errors(channels.POSTS_PERMISSION):
            return await channels.browse_channel(
                graph_client_for(transport, graph_token),
                team_id=team_id,
                channel_id=channel_id,
                limit=limit,
            )

    # Declared and registered in two steps rather than with `@mcp.tool`, which does both and hands
    # back the function: `add_tool` returns the registered tool, which is the only way to reach the
    # schema `_require_a_criterion` has to add to. Same registration, same metadata.
    @tool_metadata(
        name="search_messages",
        title="Search Teams Messages",
        description=_SEARCH_MESSAGES,
        annotations=_READ_ONLY,
    )
    async def search_messages(
        query: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Keywords to find in the message text or in an attachment's contents. Every "
                    + "word must appear, anywhere in the message and in any order; they are not "
                    + "matched as a phrase unless you quote them, so `release notes` finds "
                    + 'messages containing both words and `"release notes"` only messages where '
                    + "they are adjacent. Never a query language — a search operator written here "
                    + "is searched for as literal text, so use the other parameters for filters."
                ),
            ),
        ] = None,
        sender: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only messages from this person, by name, alias or email address. Prefer this "
                    + "over naming the person in `query`, which would match messages that merely "
                    + "mention them."
                ),
            ),
        ] = None,
        recipient: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only messages addressed to this person. Microsoft supports this only "
                    + "partially, for one-to-one chats, so it hides group-chat and channel "
                    + "matches: an empty result here is not evidence that no such message exists."
                ),
            ),
        ] = None,
        mentions: Annotated[
            UUID | None,
            Field(
                description=(
                    "Only messages that @-mention this user, by Microsoft Entra object id (the "
                    + "`user_id` of a sender here, or from get_me). A name will not work: "
                    + "Microsoft matches this term on the id alone."
                )
            ),
        ] = None,
        sent_after: Annotated[
            date | None,
            Field(
                description=(
                    "Only messages sent on or after this date (YYYY-MM-DD), inclusive. Applied by "
                    + "Microsoft's index, so it costs nothing extra and narrows chats and "
                    + "channels alike."
                )
            ),
        ] = None,
        sent_before: Annotated[
            date | None,
            Field(description="Only messages sent on or before this date (YYYY-MM-DD), inclusive."),
        ] = None,
        has_attachment: Annotated[
            bool | None,
            Field(
                description=(
                    "True for only messages carrying an attachment, false for only messages "
                    + "without one. Omit to search both."
                )
            ),
        ] = None,
        is_read: Annotated[
            bool | None,
            Field(
                description=(
                    "True for only messages the signed-in user has read, false for only unread "
                    + "ones. Omit to search both."
                )
            ),
        ] = None,
        mentions_me: Annotated[
            bool | None,
            Field(
                description=(
                    "True for only messages that @-mention the signed-in user, false for only "
                    + "messages that do not. Omit to search both."
                )
            ),
        ] = None,
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "How many results to skip. Start at 0 and pass the previous response's "
                    + "`next_offset` to advance; it is an index into Microsoft's results, not "
                    + "into the messages this tool returned."
                ),
            ),
        ] = 0,
        size: Annotated[
            int,
            Field(
                ge=1,
                le=message_search.MAX_RESULTS,
                description=(
                    "How many results to ask Microsoft for. Default 25, maximum "
                    + f"{message_search.MAX_RESULTS} — Microsoft documents no page size above "
                    + "that for message search."
                ),
            ),
        ] = 25,
        graph_token: str = _SEARCH_TOKEN,
    ) -> message_search.MessageSearchResults:
        criteria = message_search.SearchCriteria(
            query=query,
            sender=sender,
            recipient=recipient,
            mentions=mentions,
            sent_after=sent_after,
            sent_before=sent_before,
            has_attachment=has_attachment,
            is_read=is_read,
            mentions_me=mentions_me,
        )
        if criteria.is_empty:
            raise ToolError(_NO_CRITERIA)
        with graph_tool_errors(*message_search.GRAPH_PERMISSIONS):
            return await message_search.search_messages(
                graph_client_for(transport, graph_token),
                criteria=criteria,
                offset=offset,
                size=size,
            )

    _require_a_criterion(mcp.add_tool(search_messages))

    @mcp.tool(
        name="read_message",
        title="Read a Teams Message",
        description=_READ_MESSAGE,
        annotations=_READ_ONLY,
    )
    async def read_message(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the message to read, exactly as a search_messages result gave "
                    + "it: `teams:///chats/{chat_id}/messages/{message_id}` or "
                    + "`teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}`. No "
                    + "other scheme or shape is readable, and nothing else identifies a Teams "
                    + "message — a chat topic, a person's name or a Teams web link cannot be "
                    + "turned into one."
                ),
            ),
        ],
        graph_token: str = _READ_TOKEN,
    ) -> message_read.TeamsMessage:
        # The parser lives with `message_search` because the handle does: search is the only thing
        # that mints one, and one definition of the shape is what makes a search result readable.
        handle = message_search.message_handle(uri)
        if handle is None:
            raise ToolError(_BAD_HANDLE)
        # One permission, not both: the handle says which surface is being read, and Graph's 403
        # there can only be about that one. The token was exchanged for both because a dependency
        # is resolved before the tool sees its argument.
        with graph_tool_errors(handle.permission, not_found=_UNREADABLE):
            return await message_read.read_message(
                graph_client_for(transport, graph_token), handle=handle
            )

    @mcp.tool(
        name="list_meeting_transcripts",
        title="List a Meeting's Transcripts",
        description=_LIST_MEETING_TRANSCRIPTS,
        annotations=_READ_ONLY,
    )
    async def list_meeting_transcripts(
        meeting_uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The meeting whose transcripts to list, exactly as list_chats reported "
                    + "`meeting_uri` on a meeting chat: "
                    + "`teams:///meetings/{join_web_url}`. Copy it verbatim — it carries the "
                    + "meeting's join URL, which Microsoft matches character for character, and "
                    + "nothing else identifies a meeting to this connector."
                ),
            ),
        ],
        started_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only transcripts whose transcription began at or after this moment. This is "
                    + "how to reach one occurrence of a recurring meeting, whose occurrences all "
                    + "share a single meeting and therefore a single transcript collection. Three "
                    + "shapes are accepted and none of them fails: `2026-08-11T09:00:00+02:00` (or "
                    + "`...Z`) means the instant it names; `2026-08-11T09:00:00`, which names no "
                    + "offset, IS READ AS UTC; and a bare `2026-08-11` means that whole UTC day, "
                    + "starting at its first instant here. Pass the offset whenever what you know "
                    + "is a local time — 09:00 in Zurich is 07:00Z, and a window built in the "
                    + "wrong zone answers about the wrong hours without saying so. A window with "
                    + "no transcript inside it is an answer and not an error: `not_transcribed` "
                    + "once the window is past, `not_ready` while it is recent."
                )
            ),
        ] = None,
        started_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only transcripts whose transcription began at or before this moment. Pair it "
                    + "with `started_after` to bracket one occurrence; the same three shapes are "
                    + "accepted on the same UTC assumption, except that a bare `2026-08-11` here "
                    + "means the END of that UTC day — so the same date in both bounds is that one "
                    + "whole day. This bound is also what decides an empty answer: a window whose "
                    + "end is already well past reports `not_transcribed` rather than sending you "
                    + "back to wait, even for a recurring series with occurrences still to come."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=transcripts.MAX_TRANSCRIPTS,
                description=(
                    "How many transcripts to return. Default 20, maximum "
                    + f"{transcripts.MAX_TRANSCRIPTS}. They are the NEWEST that many of the "
                    + "window, not the first that many Microsoft happens to answer with: the "
                    + f"meeting's transcripts are read (up to {transcripts.MAX_ARTIFACT_SCAN} of "
                    + "them, which is this call's whole cost) and ordered before this cuts them, "
                    + "so asking for 3 gives the 3 latest. One meeting has one transcript per "
                    + "occurrence that was transcribed, so only a long-running recurring series "
                    + "reaches either bound; `truncated` says when one was reached."
                ),
            ),
        ] = 20,
        graph_token: str = _TRANSCRIPT_LIST_TOKEN,
    ) -> transcripts.MeetingTranscripts:
        handle = transcripts.meeting_handle(meeting_uri)
        if handle is None:
            raise ToolError(_not_a_meeting_handle("list_meeting_transcripts"))
        with graph_tool_errors(*transcripts.LISTING_PERMISSIONS):
            return await transcripts.list_meeting_transcripts(
                graph_client_for(transport, graph_token),
                handle=handle,
                started_after=started_after,
                started_before=started_before,
                limit=limit,
            )

    @mcp.tool(
        name="read_transcript",
        title="Read a Meeting Transcript",
        description=_READ_TRANSCRIPT,
        annotations=_READ_ONLY,
    )
    async def read_transcript(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The transcript to read, exactly as list_meeting_transcripts reported its "
                    + "`uri`: `teams:///transcripts/{meeting_id}/{transcript_id}`. A meeting's "
                    + "`meeting_uri` is not one of these, and no other shape is readable here."
                ),
            ),
        ],
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "How many turns to skip. Start at 0 and pass the previous response's "
                    + "`next_offset` to continue through a long meeting."
                ),
            ),
        ] = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=transcripts.MAX_TURNS,
                description=(
                    "How many turns to return. Default 200, maximum "
                    + f"{transcripts.MAX_TURNS}. Every call fetches the whole transcript from "
                    + "Microsoft, so widening this is cheaper than paging. It counts the turns "
                    + "left after `from_seconds`, `to_seconds` and `speaker`, not the meeting's."
                ),
            ),
        ] = 200,
        from_seconds: Annotated[
            float | None,
            Field(
                description=(
                    "Only turns reaching this moment or later, in seconds from when transcription "
                    + "began — the same scale as a turn's `start_seconds`, which is NOT a "
                    + "wall-clock time and NOT an offset from the start of the meeting. Inclusive, "
                    + "and matched by overlap: a turn already under way at this moment is kept "
                    + "whole rather than cut at it, which is usually the sentence that says what "
                    + "the stretch is about. Negative values are legal — Microsoft uses them for "
                    + "transcription that began after the conversation did. This narrows the "
                    + "answer, not the call: the whole transcript is fetched and parsed either way."
                )
            ),
        ] = None,
        to_seconds: Annotated[
            float | None,
            Field(
                description=(
                    "Only turns beginning at this moment or earlier, on the same scale and the "
                    + "same inclusive overlap rule: a turn still running at this moment is kept "
                    + "whole. Pair it with `from_seconds` to read one stretch of a long meeting, "
                    + "and keep the two in that order — a `from_seconds` later than this is "
                    + "refused rather than answered with an empty page."
                )
            ),
        ] = None,
        speaker: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only turns whose speaker's name contains this, ignoring case — `ada` matches "
                    + "`Ada Lovelace`. A substring rather than a whole name on purpose: Teams "
                    + "display names carry middle names, titles and tenant suffixes, and an exact "
                    + "match would answer 'they said nothing' to a spelling difference. **If the "
                    + "transcript's `speaker_attribution` is false this matches NOTHING** — that "
                    + "organisation records no speaker names, so every turn's `speaker` is null "
                    + "and no filter can match one. Read an empty answer together with that flag "
                    + "before concluding the person did not speak, and drop this filter to see the "
                    + "turns themselves. Omit it to read every speaker; a blank value is refused "
                    + "rather than read as 'everyone'."
                ),
            ),
        ] = None,
        graph_token: str = _TRANSCRIPT_TOKEN,
    ) -> transcripts.Transcript:
        handle = transcripts.transcript_handle(uri)
        if handle is None:
            raise ToolError(_NOT_A_TRANSCRIPT_HANDLE)
        # The two rules a schema cannot carry, refused here for the reason search_messages refuses
        # a criterion-less search: each would otherwise be answered with an empty page, and an
        # empty page is indistinguishable from a meeting in which nobody said anything.
        if from_seconds is not None and to_seconds is not None and from_seconds > to_seconds:
            raise ToolError(_INVERTED_TIME_WINDOW)
        if speaker is not None and not speaker.strip():
            raise ToolError(_BLANK_SPEAKER)
        with graph_tool_errors(transcripts.TRANSCRIPT_PERMISSION, not_found=_TRANSCRIPT_UNREADABLE):
            return await transcripts.read_transcript(
                graph_client_for(transport, graph_token),
                handle=handle,
                offset=offset,
                limit=limit,
                from_seconds=from_seconds,
                to_seconds=to_seconds,
                speaker=speaker,
            )

    @mcp.tool(
        name="list_meeting_recordings",
        title="List a Meeting's Recordings",
        description=_LIST_MEETING_RECORDINGS,
        annotations=_READ_ONLY,
    )
    async def list_meeting_recordings(
        meeting_uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The meeting whose recordings to list, exactly as list_chats reported "
                    + "`meeting_uri` on a meeting chat: `teams:///meetings/{join_web_url}` — the "
                    + "same handle list_meeting_transcripts takes. Copy it verbatim; it carries "
                    + "the meeting's join URL, which Microsoft matches character for character."
                ),
            ),
        ],
        started_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only recordings that began at or after this moment. This is how to reach one "
                    + "occurrence of a recurring meeting, whose occurrences all share a single "
                    + "meeting and therefore a single recording collection. Three shapes are "
                    + "accepted and none of them fails: `2026-08-11T09:00:00+02:00` (or `...Z`) "
                    + "means the instant it names; `2026-08-11T09:00:00`, which names no offset, "
                    + "IS READ AS UTC; and a bare `2026-08-11` means that whole UTC day, starting "
                    + "at its first instant here. Pass the offset whenever what you know is a "
                    + "local time — 09:00 in Zurich is 07:00Z. A window with no recording inside "
                    + "it is an answer and not an error: `not_recorded` once the window is past, "
                    + "`not_ready` while it is recent."
                )
            ),
        ] = None,
        started_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only recordings that began at or before this moment. Pair it with "
                    + "`started_after` to bracket one occurrence; the same three shapes are "
                    + "accepted on the same UTC assumption, except that a bare `2026-08-11` here "
                    + "means the END of that UTC day — so the same date in both bounds is that one "
                    + "whole day. This bound is also what decides an empty answer: a window whose "
                    + "end is already well past reports `not_recorded` rather than sending you "
                    + "back to wait, even for a recurring series with occurrences still to come."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=recordings.MAX_RECORDINGS,
                description=(
                    "How many recordings to return. Default 20, maximum "
                    + f"{recordings.MAX_RECORDINGS}. They are the NEWEST that many of the window, "
                    + "not the first that many Microsoft happens to answer with: the meeting's "
                    + f"recordings are read (up to {transcripts.MAX_ARTIFACT_SCAN} of them, which "
                    + "is this call's whole cost) and ordered before this cuts them, so asking for "
                    + "3 gives the 3 latest. A meeting has one recording per occurrence that was "
                    + "recorded — two if somebody stopped and restarted — so only a long-running "
                    + "recurring series reaches either bound; `truncated` says when one was "
                    + "reached."
                ),
            ),
        ] = 20,
        graph_token: str = _RECORDING_LIST_TOKEN,
    ) -> recordings.MeetingRecordings:
        handle = transcripts.meeting_handle(meeting_uri)
        if handle is None:
            raise ToolError(_not_a_meeting_handle("list_meeting_recordings"))
        with graph_tool_errors(*recordings.LISTING_PERMISSIONS):
            return await recordings.list_meeting_recordings(
                graph_client_for(transport, graph_token),
                handle=handle,
                started_after=started_after,
                started_before=started_before,
                limit=limit,
            )


def _require_a_criterion(tool: Tool) -> None:
    """Put "at least one criterion" in the tool's schema, where a client can enforce it.

    FastMCP derives an input schema from the function signature, and a signature has no way to say
    that a set of optional parameters cannot all be omitted — so the rule would otherwise live only
    in the description and in the tool's own runtime check. `anyOf` over one-element `required`
    lists is the JSON Schema spelling of it, and the registered tool's schema is where it goes.
    The runtime check stays: FastMCP validates arguments against the signature rather than against
    this schema, so a client that ignores it must still be refused.
    """
    tool.parameters["anyOf"] = [{"required": [name]} for name in message_search.CRITERIA]
