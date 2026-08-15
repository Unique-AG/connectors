"""`read_message` — one Microsoft Teams message in full, from the handle another tool minted.

`search_messages` cannot answer "what did they actually say". Graph's search index returns a
reduced `chatMessage` projection with **no `body`** — "The search Teams API doesn't return all
properties defined in chatMessage. You can use the Teams API to retrieve more details about any
single message" (https://learn.microsoft.com/en-us/graph/search-concept-chat-messages) — so a hit
is metadata plus a handle, and this is the tool that turns the handle back into a message.

Three things make this tool what it is, and each of them is a decision rather than a detail.

**It reads one of two surfaces, and the handle is what says which.** Graph addresses a Teams
message under a chat and under a team's channel, with a different endpoint and a different
delegated permission for each. Nothing in the argument a model passes says which of them it is
except the handle's own shape, which is why the handle is what decides both.

**Three failures are kept distinct, and only one of them is ours.** A malformed handle is ours to
explain, so its refusal shows the two shapes and names the tool that produces them. Graph's 403 is
a missing permission and names *one* — `MessageHandle.permission`, the one the surface being read is
read under — because naming the other would send an administrator after a permission that was never
missing. Graph's 404 is the one that must not be reported as "the message never existed": Graph
answers deleted, never-existed and invisible-to-this-user identically and never says which of them
it meant. That 404 also suppresses the generic advice — "check the id came from a tool response
verbatim" — because the handle *did* come from a tool response, and telling a caller to check it is
telling them to retry a call that cannot succeed.

**Two messages have no text and neither is an empty one.** A deleted message carries a tombstone
whose body must not be presented as content, and a system event message has no author and no text
anywhere in Graph, because the sentence Teams shows ("Ada joined the chat") is written by the Teams
client and never sent. `deleted_at` and `event` are what say which, and the description says to
report the reason rather than the emptiness.

What this file does not own is the handle grammar (`shared/handles.py`, so the handle
`search_messages` minted is read by the one parser that wrote it, and so that which permission a
surface is read under is decided once), the message shape and its normalisation out of Teams HTML
(`shared/messages.py`, so a message a search found and the same message read here are the same type
normalised by the same function), and the token and refusal wording (`shared/seam.py`, so this
tool's 403 sounds like every other tool's). Everything else — the name, the description, the
argument, the request and every refusal below — is here.
"""

from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.chats.item.messages.item.chat_message_item_request_builder import (
    ChatMessageItemRequestBuilder as ChatMessageRequestBuilder,
)
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.teams.item.channels.item.messages.item.chat_message_item_request_builder import (  # noqa: E501
    ChatMessageItemRequestBuilder as ChannelMessageRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_mcp.graph_client import graph_client_for, graph_errors
from office_mcp.shared.handles import (
    CHANNEL_PERMISSION,
    CHAT_PERMISSION,
    MessageHandle,
    message_handle,
)
from office_mcp.shared.messages import TeamsMessage, message_of
from office_mcp.shared.seam import READ_ONLY, graph_token, graph_tool_errors

TOOL_NAME = "read_message"

# What the token exchange has to ask for: both, because the exchange happens before the tool sees
# its argument and so before anything knows which surface this call will read. Reading a message is
# `Chat.Read` in a chat and `ChannelMessage.Read.All` in a channel — the permissions are per surface
# (https://learn.microsoft.com/en-us/graph/api/chatmessage-get) — and `MessageHandle.permission` is
# what names the one a given read was actually made under, which is what a 403 is worded from.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

# Built once at import: a call inside a parameter default rebuilds the descriptor on every
# registration and is a lint error in both of this repo's checkers.
_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

_DESCRIPTION = """\
Read one Microsoft Teams message in full, from the `uri` handle a search_messages result carries: \
the whole message text, who sent it, who was @-mentioned, what was attached, and whether it has \
been edited or deleted.

This is the other half of search_messages, and the only route to the text of a message a search \
found. Microsoft's search index answers with a reduced view of a message that contains no body at \
all, so a search result carries only Microsoft's `summary` snippet. Read the message here whenever \
the answer depends on what somebody actually said rather than on the fact that a matching message \
exists — and never present a snippet as the message.

`uri` takes a handle this connector produced, in one of exactly two shapes:
  teams:///chats/{chat_id}/messages/{message_id}
  teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}
Nothing else is readable here. No handle of this connector's names mail, a calendar event, a file \
or a SharePoint page, and nothing turns a person's name or a chat topic into one — pass the `uri` \
from a tool result verbatim.

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
    + "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000. Copy the `uri` of a tool "
    + "result rather than assembling one. This reader serves Teams messages only: no mail, files "
    + "or sites are addressable in this connector at all. Retrying this value will fail "
    + "identically."
)

# Graph's 404 on a well-formed handle, which is a different failure from a malformed one and must
# not be reported as the message never having existed.
_UNREADABLE = (
    "Microsoft 365 would not return this message. The handle is well formed, so this is not a bad "
    + "argument — and it is not evidence that the message does not exist: Graph answers 'deleted', "
    + "'never existed' and 'the signed-in user may not see it' with the same 404, and does not say "
    + "which of them it meant. Report that the message could not be read, never that it was never "
    + "written. Retrying will not help and this connector has no other route to the text. Report "
    + "the search snippet with its sender and date, say the full text could not be retrieved, and "
    + "stop looking."
)

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


async def read_message(client: GraphServiceClient, *, handle: MessageHandle) -> TeamsMessage:
    """The message `handle` addresses. One Graph request, whichever surface it lives on.

    `chatmessage-get` "doesn't support the OData query parameters", so there is no `$select` to
    narrow it with and no `$expand` to widen it: mentions and attachments arrive with the message.
    """
    with graph_errors():
        message = await _get(client, handle)

    assert message is not None, "Graph answered a message read with no message"
    return message_of(message, handle=handle)


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
    messages = (
        client.teams.by_team_id(handle.team_id).channels.by_channel_id(handle.channel_id).messages
    )
    return await messages.by_chat_message_id(handle.message_id).get(
        request_configuration=RequestConfiguration[_ChannelMessageQuery](headers=_headers())
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


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this tool against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tool
    borrows it per call and never owns it. `create_app` closes it on shutdown.
    """

    @mcp.tool(
        name=TOOL_NAME,
        title="Read a Teams Message",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def read_teams_message(
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
        graph_token: str = _TOKEN,
    ) -> TeamsMessage:
        # The parser is `shared/handles.py`'s, not this file's: search is what mints a handle and
        # this is what reads one back, and one definition of the shape is what makes a search
        # result readable at all.
        handle = message_handle(uri)
        if handle is None:
            raise ToolError(_BAD_HANDLE)
        # One permission, not both: the handle says which surface is being read, and Graph's 403
        # there can only be about that one. The token was exchanged for both because a dependency
        # is resolved before the tool sees its argument.
        with graph_tool_errors(handle.permission, not_found=_UNREADABLE):
            return await read_message(graph_client_for(transport, graph_token), handle=handle)
