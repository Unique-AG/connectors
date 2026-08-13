"""The MCP tools, and the one seam every later tool inherits.

A tool is a function that (1) is handed the caller's Microsoft Graph token, (2) borrows the shared
HTTP transport to call Graph as that caller, and (3) reports a Graph failure as advice. There is
no registry, no base class and no decorator of our own: `register_tools` closes over the transport
`create_app` built, which is the whole of what FastMCP's plain-function tool signature would
otherwise need a process-wide service holder for.

The token comes from `EntraOBOToken`, FastMCP's own On-Behalf-Of dependency: it takes the Entra
token the caller presented (audience `api://{client_id}`, useless against Graph) and exchanges it
for a Graph one in the scopes named here. It is a dependency default, so it never appears in the
tool's input schema — the model cannot see it and cannot supply it.
"""

from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.azure import EntraOBOToken
from pydantic import Field

from office_mcp.features import chats, identity
from office_mcp.graph_client import graph_client_for
from office_mcp.server.errors import graph_tool_errors

# A Graph delegated permission, as a scope the On-Behalf-Of exchange can ask for. Graph accepts a
# bare permission name at the authorize endpoint too, but only because it is the default resource;
# the full form is unambiguous and is what FastMCP's own examples use.
_GRAPH_SCOPE_PREFIX = "https://graph.microsoft.com/"


def _scope(permission: str) -> str:
    return f"{_GRAPH_SCOPE_PREFIX}{permission}"


# What sign-in must ask Entra for, so that the On-Behalf-Of exchange has something to redeem: a
# Graph permission the user (or an administrator) never consented to cannot be obtained later, and
# the exchange fails with AADSTS65001 rather than with anything a tool could explain. `create_app`
# passes this to the auth provider — which is why it is the union of every tool's permission, and
# why it lives beside the tools that determine it.
GRAPH_SCOPES: tuple[str, ...] = (
    _scope(identity.GRAPH_PERMISSION),
    _scope(chats.GRAPH_PERMISSION),
)

# The On-Behalf-Of dependency each tool declares as its token parameter's default, one per Graph
# permission. Built here rather than inline because a call inside a parameter default rebuilds the
# descriptor on every registration and is a lint error in both of this repo's checkers. Sharing one
# instance is safe: FastMCP enters it per call and it holds nothing but its scopes. The declared
# type is `str` because a token is what FastMCP injects in its place — the tool body never sees
# this object.
_IDENTITY_TOKEN: str = EntraOBOToken([_scope(identity.GRAPH_PERMISSION)])
_CHATS_TOKEN: str = EntraOBOToken([_scope(chats.GRAPH_PERMISSION)])

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
name; Graph caps that list at {chats.MEMBERS_PER_CHAT} members per chat and `members_truncated` \
says when the cap was hit. Set `include_member_emails` when two members share a display name.

There is no pagination. `limit` is a window on the most recent chats and `truncated` says whether \
the user has more than fit in it — widen `limit` (up to {chats.MAX_CHATS}, Graph's own maximum \
for this collection) rather than looking for a cursor. The signed-in user's own notes-to-self \
chat is usually the oneOnOne chat whose only member is them (call whoami to know who that is).\
"""

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
