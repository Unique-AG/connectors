"""The MCP tools, and the one seam every later tool inherits.

A tool is a function that (1) is handed the caller's Microsoft Graph token, (2) borrows the shared
HTTP transport to call Graph as that caller, and (3) reports a Graph failure as advice. There is
no registry, no base class and no decorator of our own: `register_tools` closes over the transport
`create_app` built, which is the whole of what FastMCP's plain-function tool signature would
otherwise need a process-wide service holder for.

The token comes from `EntraOBOToken`, FastMCP's own On-Behalf-Of dependency: it takes the Entra
token the caller presented (audience `api://{client_id}`, useless against Graph) and exchanges it
for a Graph one in the scopes named here. It is a dependency default, so it never appears in the
tool's input schema — the model cannot see it and cannot supply it. `_GraphToken` wraps it for
one reason: a dependency is resolved *outside* the tool body, so an exchange Entra refuses cannot
be explained by anything the body does.
"""

from datetime import date
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

from office_mcp.features import chats, identity, message_read, message_search
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
            *message_search.GRAPH_PERMISSIONS,
            *message_read.GRAPH_PERMISSIONS,
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
_SEARCH_TOKEN: str = _graph_token(*message_search.GRAPH_PERMISSIONS)
_READ_TOKEN: str = _graph_token(*message_read.GRAPH_PERMISSIONS)

_WHOAMI = """\
Return the signed-in Microsoft 365 user's own profile: `id`, `display_name`, `mail`, \
`user_principal_name` and `job_title`.

Call this before anything that turns on who "I", "me" or "my" is: filtering a mail or message \
search to the signed-in user, deciding which participant of a chat is them, or addressing them by \
name. It is one cheap request and its answer is stable for the session.

`mail` is the canonical primary SMTP address and the right value to match a sender or recipient \
against — but it is null for guest and unlicensed accounts, and `user_principal_name` (Microsoft's \
`userPrincipalName`) is then the best available identifier. Do not treat the two as \
interchangeable when both are present: a tenant can issue a user_principal_name on a different \
domain from the mail address, so matching message addresses against it can silently return \
nothing. Compare `id` — the immutable directory object id — against user ids from other tools; \
compare `mail` against addresses.\
"""

_LIST_CHATS = f"""\
List the Microsoft Teams chats the signed-in user is a member of — one-to-one, group and meeting \
chats — most recently active first, with each chat's id, type, topic, last-message time and (for \
unnamed chats) its members.

Use it to find the `chat_id` that a chat-scoped tool needs, or to see which conversations are \
live. This returns chats only: Teams channels live inside teams and are not part of this list.

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
chat is usually the oneOnOne chat whose only member is them (call whoami to know who that is).\
"""

_SEARCH_MESSAGES = f"""\
Search the Microsoft Teams messages the signed-in user can see — every one-to-one chat, group \
chat, meeting chat and channel they belong to — by keywords, sender, mentions, date, attachments \
and read state. Messages from ANY participant match, not only the user's own; call whoami if you \
need to know who the user is.

A result is metadata plus a snippet, by necessity. Microsoft's search index answers with a reduced \
view of a message that contains no message body at all, so `summary` — Microsoft's own excerpt, \
truncated with `...` where it was cut — is the only text here. Every hit carries a `uri` handle \
identifying that exact message; pass it to read_message for the real text, the attachments and the \
mentions. Never present `summary` as the whole message, and never conclude from it that the \
message does not say more.

There is no result total, and this is not an omission: Microsoft Graph reports a per-page count \
rather than a match count for Teams messages, so a total would be a fabrication. Page by passing \
`next_offset` back as `offset` while `more_results_available` is true. A page can hold fewer than \
`size` messages — offsets index Graph's own results, and system messages ("Ada joined the chat") \
are dropped from ours because Graph gives them neither an author nor any text.

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

This is the other half of search_messages, and the only route to a message's text. Microsoft's \
search index answers with a reduced view of a message that contains no body at all, so a search \
result carries only Microsoft's `summary` snippet. Read the message here whenever the answer \
depends on what somebody actually said rather than on the fact that a matching message exists — \
and never present a snippet as the message.

`uri` takes a handle this connector produced, in one of exactly two shapes:
  teams:///chats/{chat_id}/messages/{message_id}
  teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}
Nothing else is readable. This connector serves Microsoft Teams messages, so no handle here names \
mail, a calendar event, a file, a SharePoint page or a meeting transcript, and nothing turns a \
person's name or a chat topic into one — pass the `uri` from a search result verbatim.

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
    "read_message takes a `uri` handle that search_messages produced, and this is not one. A "
    + "readable handle has one of exactly two shapes:\n"
    + "  teams:///chats/{chat_id}/messages/{message_id}\n"
    + "  teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}\n"
    + "with the ids percent-encoded, e.g. "
    + "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000. Copy the `uri` of a search "
    + "result rather than assembling one, and note that this connector reads Teams messages only — "
    + "no mail, files, sites or meetings are addressable here. Retrying this value will fail "
    + "identically."
)

# Graph's 404 on a well-formed handle, which is a different failure from a malformed one and must
# not be reported as the message never having existed.
_UNREADABLE = (
    "Microsoft 365 would not return this message. The handle is well formed, so this is not a bad "
    + "argument — and it is not evidence that the message does not exist: Graph answers 'deleted', "
    + "'never existed' and 'the signed-in user may not see it' with the same 404, and does not say "
    + "which of them it meant. Report that the message could not be read, never that it was never "
    + "written. Retrying will not help and this connector has no other route to the text. (A reply "
    + "inside a channel thread is also addressed under its parent post, which this handle shape "
    + "cannot express.)"
)

_READ_ONLY = {"readOnlyHint": True, "openWorldHint": True}


def register_tools(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this server's tools against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tools
    below borrow it per call and never own it. `create_app` closes it on shutdown.
    """

    @mcp.tool(name="whoami", title="Who Am I", description=_WHOAMI, annotations=_READ_ONLY)
    async def whoami(graph_token: str = _IDENTITY_TOKEN) -> identity.SignedInUser:
        with graph_tool_errors(identity.GRAPH_PERMISSION):
            return await identity.get_signed_in_user(graph_client_for(transport, graph_token))

    @mcp.tool(
        name="list_chats", title="List My Chats", description=_LIST_CHATS, annotations=_READ_ONLY
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
                    + "`user_id` of a sender here, or `id` from whoami). A name will not work: "
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
        handle = message_read.message_handle(uri)
        if handle is None:
            raise ToolError(_BAD_HANDLE)
        # One permission, not both: the handle says which surface is being read, and Graph's 403
        # there can only be about that one. The token was exchanged for both because a dependency
        # is resolved before the tool sees its argument.
        with graph_tool_errors(handle.permission, not_found=_UNREADABLE):
            return await message_read.read_message(
                graph_client_for(transport, graph_token), handle=handle
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
