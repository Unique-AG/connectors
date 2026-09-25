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

STEP_CHAT_MESSAGE = "chat_message"
STEP_CHANNEL_MESSAGE = "channel_message"
STEP_CHANNEL_REPLY = "channel_reply"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000"
}

GRAPH_CALL_NARROWS_TO: tuple[str, ...] = (CHAT_PERMISSION,)

_DESCRIPTION = (
    "Reads one Teams message in full — text, sender, mentions, attachments, reactions, and "
    "edit or delete status — from a handle another tool produced."
)

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

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this message. The handle is well formed, so this is not a bad "
    + "argument. It is also not evidence that the message does not exist. Graph answers "
    + "'deleted', 'never existed', and 'the signed-in user cannot see it' with the same 404. "
    + "Graph does not say which of these it meant. Report that this tool did not read the "
    + "message, never that it was never written. Retrying will not help, and this connector has "
    + "no other route to the text. One well-formed handle always fails this way: a reply in a "
    + "channel thread is addressed under the post it answers. A search result does not identify "
    + "that post, so a search hit that is a reply cannot be read from its own handle. "
    + "teams_browse_channel is the only tool that emits a reply's own handle. It reaches the "
    + f"newest {MAX_REPLIES_PER_POST} replies of each post on the channel's first page, and no "
    + "further. It follows neither Microsoft's cursor into an older part of a thread, nor the "
    + "one into older posts. This is because a given channel allows this whole connector about "
    + "one request a second, across the whole tenant. Browse that channel once. If the reply is "
    + "not in what comes back, there is no route to its full text, and a second browse returns "
    + "the same window. Report the search snippet with its sender and date. Say that this tool "
    + "did not retrieve the full text. Then stop looking."
)

_PREFER_UNKNOWN_ENUMS = ("Prefer", "include-unknown-enum-members")

type _ChatMessageQuery = ChatMessageRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters
type _ChannelMessageQuery = (
    ChannelMessageRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters
)
type _ChannelReplyQuery = ChannelReplyRequestBuilder.ChatMessageItemRequestBuilderGetQueryParameters


async def teams_read_message(client: GraphServiceClient, *, handle: MessageHandle) -> TeamsMessage:
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
                    "The message handle (`uri`) from a teams_search_messages or "
                    "teams_browse_channel result."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage:
        handle = message_handle(uri)
        if handle is None:
            raise ToolError(_BAD_HANDLE)
        await narrowed_to(ctx, handle.permission)
        return await teams_read_message(client, handle=handle)
