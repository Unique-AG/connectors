"""`teams_read_message`: one Microsoft Teams message in full, from a handle another tool
made."""

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

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.handles import (
    CHANNEL_PERMISSION,
    CHAT_PERMISSION,
    MessageHandle,
    message_handle,
)
from office_365_mcp.shared.messages import MAX_REPLIES_PER_POST, TeamsMessage
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller, narrowed_to

TOOL_NAME = "teams_read_message"

# Three steps, not one. With a single step, a tenant that refuses channel messages looks like a
# merely slow tool. The name comes from the handle's shape, never from the handle itself.
STEP_CHAT_MESSAGE = "chat_message"
STEP_CHANNEL_MESSAGE = "channel_message"
STEP_CHANNEL_REPLY = "channel_reply"

# A read uses `Chat.Read` in a chat and `ChannelMessage.Read.All` in a channel. The token exchange
# requests both, because the handle is parsed after the exchange.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000"
}

# A chat handle's refusal names only the chat permission. Naming the channel one too sends an
# administrator after a permission that was never missing.
GRAPH_CALL_NARROWS_TO: tuple[str, ...] = (CHAT_PERMISSION,)

_DESCRIPTION = """\
Read one Teams message in full: the whole text, sender, @-mentions, attachments, and edit or \
delete status. Call it on the `uri` of a teams_search_messages hit whenever the answer depends on \
what somebody actually said — a hit carries a snippet and no message body. A message \
teams_browse_channel returned is already complete and needs no read. `uri` must be a handle a tool \
result carried. No name, chat topic, or Teams link becomes one.\
"""

_BAD_HANDLE = (
    "teams_read_message takes a `uri` handle that teams_search_messages or teams_browse_channel "
    + "produced, and this "
    + "is not one. A readable handle has one of exactly three shapes:\n"
    + "  teams:///chats/{chat_id}/messages/{message_id}\n"
    + "  teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}\n"
    + "  teams:///teams/{team_id}/channels/{channel_id}/messages/{root_id}/replies/{reply_id}\n"
    + "with the ids percent-encoded, for example "
    + "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000. Copy the `uri` of a tool "
    + "result rather than assembling one. This reader serves Teams messages only: no mail, files "
    + "or sites are addressable in this connector at all. Retrying this value will fail "
    + "identically."
)

# The default 404 advice, to check the id came from a tool response verbatim, is wrong here because
# the handle did.
GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this message. The handle is well formed, so this is not a bad "
    + "argument — and it is not evidence that the message does not exist: Graph answers 'deleted', "
    + "'never existed' and 'the signed-in user cannot see it' with the same 404, and does not say "
    + "which of them it meant. Report that this tool did not read the message, never that it was "
    + "never "
    + "written. Retrying will not help and this connector has no other route to the text. One "
    + "well-formed handle always fails this way: a reply in a channel thread is addressed under "
    + "the post it answers, and a search result does not identify that post — so a search hit that "
    + "is a reply cannot be read from its own handle. teams_browse_channel is the only tool that "
    + "emits a "
    + "reply's own handle, and it reaches the newest "
    + f"{MAX_REPLIES_PER_POST} replies of each post on the channel's first page and no "
    + "further: it follows neither Microsoft's cursor into an older part of a thread nor the one "
    + "into older posts, because a given channel allows this whole connector about one request a "
    + "second across the tenant. So browse that channel once. If the reply is not in what comes "
    + "back, there is no route to its full text, and a second browse returns the same window. "
    + "Report the search snippet with its sender and date, say this tool did not retrieve the "
    + "full text, and stop looking."
)

# Without this header Graph answers `systemEventMessage` as `unknownFutureValue`. `chatEvent` and
# `typing` show neither a null `from` nor an `eventDetail`, so `messageType` is the only signal.
_PREFER_UNKNOWN_ENUMS = ("Prefer", "include-unknown-enum-members")

type _ChatMessageQuery = ChatMessageRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters
type _ChannelMessageQuery = (
    ChannelMessageRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters
)
type _ChannelReplyQuery = ChannelReplyRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters


async def teams_read_message(client: GraphServiceClient, *, handle: MessageHandle) -> TeamsMessage:
    """The message `handle` addresses. One request. The endpoint supports no `$select` or
    `$expand`, so mentions and attachments always arrive with it.
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
        # A reply is addressed under its parent post. The reply id alone is a 404.
        # `by_chat_message_id1` is the generated name for the second message id in that path.
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
    """Built per request. Adding to the shared default collection affects every Graph call."""
    headers = HeadersCollection()
    headers.add(*_PREFER_UNKNOWN_ENUMS)
    return headers


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
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
                    "The handle a tool result carried, verbatim. Exactly three shapes are "
                    + "readable:\n"
                    + "  teams:///chats/{chat_id}/messages/{message_id}\n"
                    + "  teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}\n"
                    + "  teams:///teams/{team_id}/channels/{channel_id}/messages/{root_id}"
                    + "/replies/{reply_id}\n"
                    + "teams_search_messages emits the first two. The third only "
                    + "teams_browse_channel "
                    + "emits: "
                    + "Microsoft addresses a reply under the post it answers, and a search result "
                    + "does not say which post that is. No other shape is readable. Chat topics, "
                    + "person names and Teams web links cannot be turned into handles."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage:
        handle = message_handle(uri)
        if handle is None:
            raise ToolError(_BAD_HANDLE)
        # The 403 table is built at startup and never sees the handle. This names the surface read.
        await narrowed_to(ctx, handle.permission)
        return await teams_read_message(client, handle=handle)
