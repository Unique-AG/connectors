"""`read_message` — one Microsoft Teams message in full, from a handle another tool creates.

Search cannot answer "what did they actually say": Graph's search index has no message body, only
Microsoft's `summary` snippet. This tool resolves a search result's handle into the full message.

The handle decides which surface to read. Graph puts a Teams message in a chat or a channel, each
with its own endpoint and permission, and a handle's shape names the surface it addresses.

Three failures are kept apart. A malformed handle is ours to explain. Graph's 403 is about that one
surface's permission only, because naming the other would send an administrator after a permission
that was never missing. Graph's 404 means deleted, never existed, or invisible to this user, without
saying which, so the tool must not claim the message never existed. The generic advice to check the
id is wrong here: the id came from a tool.

Two messages have no text. A deleted message carries a tombstone, which must not read as content. A
system event ("Ada joined") has no author and no text in Graph, because Teams writes the sentence
itself. Report the event, not the emptiness.
"""

from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
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
from msgraph.generated.teams.item.channels.item.messages.item.replies.item.chat_message_item_request_builder import (  # noqa: E501
    ChatMessageItemRequestBuilder as ChannelReplyRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_mcp.graph_client import graph_errors, graph_step
from office_mcp.shared.handles import (
    CHANNEL_PERMISSION,
    CHAT_PERMISSION,
    MessageHandle,
    message_handle,
)
from office_mcp.shared.messages import MAX_REPLIES_PER_POST, TeamsMessage
from office_mcp.shared.seam import READ_ONLY, graph_client_for_caller, narrowed_to

TOOL_NAME = "read_message"

# The surfaces this tool reads, as the step instruments count them. Three rather than one, for the
# same reason `GRAPH_CALL_NARROWS_TO` names one permission rather than two: a chat message, a
# channel post and a channel reply are three Graph requests with three failure modes, and a single
# step would report a tenant that refuses channel messages as a tool that is merely slow. The step
# name comes from the handle's shape, which is code, never from the handle itself.
STEP_CHAT_MESSAGE = "chat_message"
STEP_CHANNEL_MESSAGE = "channel_message"
STEP_CHANNEL_REPLY = "channel_reply"

# A read uses `Chat.Read` in a chat and `ChannelMessage.Read.All` in a channel. The token exchange
# requests both, because the handle is parsed after the exchange.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

# One call that reaches Graph, read by `tools/__init__.py` into the coverage table
# `tests/test_error_mapping.py` refuses every registered tool from. The ids are invented, but the
# shape must be one this tool accepts: an argument it rejects never reaches Graph to be refused.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000"
}

# What the call above is refused for, and not the tuple this tool holds. A message is read on one
# surface, so a chat handle's refusal names the chat permission alone: naming the channel one too
# would send an administrator after a permission that was never missing. `narrowed_to` below makes
# the same statement per call, from the argument, at run time.
GRAPH_CALL_NARROWS_TO: tuple[str, ...] = (CHAT_PERMISSION,)

_DESCRIPTION = """\
Read one Microsoft Teams message in full, from the `uri` handle search_messages produces: the \
whole text, sender, @-mentions, attachments, and edit/delete status.

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
from a tool result verbatim. The third shape above is the one only browse_channel emits: Microsoft \
addresses a reply in a channel thread under the post it answers, and a search result does not say \
which post that is.

`text` is plain text normalised from Teams HTML: mentions read as `@Name`, list items as `- `, \
attachments as `[attachment: name]`, inline images as `[image]`, cards as `[card]`. The `mentions` \
and `attachments` fields name what those placeholders refer to. A message with JSON or code is \
somebody's words and is returned in full. `[card]` appears only where `attachments` names a card.

Two messages have no text. A deleted message returns `deleted_at` and null `text` — report the \
deletion. A system event — somebody joining, a call ending, a chat renamed — has no author and no \
text in Graph (Teams writes the displayed sentence itself). For those, `event` names what \
happened. Do not invent the wording.\
"""

_BAD_HANDLE = (
    "read_message takes a `uri` handle that search_messages or browse_channel produced, and this "
    + "is not one. A readable handle has one of exactly three shapes:\n"
    + "  teams:///chats/{chat_id}/messages/{message_id}\n"
    + "  teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}\n"
    + "  teams:///teams/{team_id}/channels/{channel_id}/messages/{root_id}/replies/{reply_id}\n"
    + "with the ids percent-encoded, e.g. "
    + "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000. Copy the `uri` of a tool "
    + "result rather than assembling one. This reader serves Teams messages only: no mail, files "
    + "or sites are addressable in this connector at all. Retrying this value will fail "
    + "identically."
)

# Read by `tools/__init__.py` into the advice table `GraphAdviceMiddleware` words a 404 from. Public
# for that reason: the default advice ("check the id came from a tool response verbatim") is wrong
# here, because the handle did come from one.
GRAPH_NOT_FOUND = (
    "Microsoft 365 would not return this message. The handle is well formed, so this is not a bad "
    + "argument — and it is not evidence that the message does not exist: Graph answers 'deleted', "
    + "'never existed' and 'the signed-in user may not see it' with the same 404, and does not say "
    + "which of them it meant. Report that the message could not be read, never that it was never "
    + "written. Retrying will not help and this connector has no other route to the text. One "
    + "well-formed handle always fails this way: a reply in a channel thread is addressed under "
    + "the post it answers, and a search result does not identify that post — so a search hit that "
    + "is a reply cannot be read from its own handle. browse_channel is the only tool that emits a "
    + "reply's own handle, and it reaches the newest "
    + f"{MAX_REPLIES_PER_POST} replies of each post on the channel's first page and no "
    + "further: it follows neither Microsoft's cursor into an older part of a thread nor the one "
    + "into older posts, because a given channel allows this whole connector about one request a "
    + "second across the tenant. So browse that channel once; if the reply is not in what comes "
    + "back there is no route to its full text, and a second browse returns the same window. "
    + "Report the search snippet with its sender and date, say the full text could not be "
    + "retrieved, and stop looking."
)

# Without this header, Graph answers `systemEventMessage` as `unknownFutureValue`. A null `from` or
# a populated `eventDetail` already marks most system events, but `chatEvent` and `typing` show
# neither, so `messageType` is the only way to name them and this header keeps it legible.
_PREFER_UNKNOWN_ENUMS = ("Prefer", "include-unknown-enum-members")

type _ChatMessageQuery = ChatMessageRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters
type _ChannelMessageQuery = (
    ChannelMessageRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters
)
type _ChannelReplyQuery = ChannelReplyRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters


async def read_message(client: GraphServiceClient, *, handle: MessageHandle) -> TeamsMessage:
    """The message `handle` addresses. One Graph request, whichever surface it lives on.

    This endpoint does not support `$select` or `$expand`. Mentions and attachments always arrive
    with the message.
    """
    with graph_errors(TOOL_NAME):
        message = await _get(client, handle)

    assert message is not None, "Graph answered a message read with no message"
    return TeamsMessage.from_message(message, handle=handle)


async def _get(client: GraphServiceClient, handle: MessageHandle) -> ChatMessage | None:
    if handle.chat_id is not None:
        with graph_step(STEP_CHAT_MESSAGE):
            return await (
                client.chats.by_chat_id(handle.chat_id)
                .messages.by_chat_message_id(handle.message_id)
                .get(
                    request_configuration=RequestConfiguration[_ChatMessageQuery](
                        headers=_headers()
                    )
                )
            )
    assert handle.team_id is not None and handle.channel_id is not None, (
        "a handle addresses either a chat or a team channel"
    )
    messages = (
        client.teams.by_team_id(handle.team_id).channels.by_channel_id(handle.channel_id).messages
    )
    if handle.reply_to_id is not None:
        # A reply is addressed under the post it replies to, never beside it: the reply id alone
        # is a 404. `by_chat_message_id1` is the generated name for the second message id in that
        # path, after the parent post's.
        with graph_step(STEP_CHANNEL_REPLY):
            return await (
                messages.by_chat_message_id(handle.reply_to_id)
                .replies.by_chat_message_id1(handle.message_id)
                .get(
                    request_configuration=RequestConfiguration[_ChannelReplyQuery](
                        headers=_headers()
                    )
                )
            )
    with graph_step(STEP_CHANNEL_MESSAGE):
        return await messages.by_chat_message_id(handle.message_id).get(
            request_configuration=RequestConfiguration[_ChannelMessageQuery](headers=_headers())
        )


def _headers() -> HeadersCollection:
    """A `HeadersCollection` with the `Prefer` header, built per request rather than shared:
    adding to the default would affect every Graph request this connector makes.
    """
    headers = HeadersCollection()
    headers.add(*_PREFER_UNKNOWN_ENUMS)
    return headers


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Register this tool. The tool borrows `transport` per call."""
    # Built here because this is where `transport` is: the dependency closes over it, and the
    # default below is evaluated when the `def` runs, inside this call. The default holds a name,
    # not a call. A call there is ruff's B008.
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

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
                    "The handle search_messages produced, exactly: "
                    + "`teams:///chats/{chat_id}/messages/{message_id}` or "
                    + "`teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}`. "
                    + "No other shape is readable. Chat topics, person names and Teams web links "
                    + "cannot be turned into handles."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage:
        handle = message_handle(uri)
        if handle is None:
            raise ToolError(_BAD_HANDLE)
        # Use only the permission for this surface. The token was exchanged for both, because the
        # handle is parsed after the exchange. The table that words a 403 is built at startup and
        # never sees the handle, so this call tells it which of the two the read was made under.
        await narrowed_to(ctx, handle.permission)
        return await read_message(client, handle=handle)
