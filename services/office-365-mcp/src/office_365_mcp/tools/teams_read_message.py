from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.handles import (
    CHANNEL_PERMISSION,
    CHAT_PERMISSION,
    MessageHandle,
    message_handle,
    not_a_message_handle,
)
from office_365_mcp.shared.messages import TeamsMessage, get_message
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller, narrowed_to

TOOL_NAME = "teams_read_message"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION, CHANNEL_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000"
}

GRAPH_CALL_NARROWS_TO: tuple[str, ...] = (CHAT_PERMISSION,)

_DESCRIPTION = (
    "Reads one Teams message in full — text, sender, mentions, attachments, reactions, and "
    "edit or delete status — from a handle another tool produced."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this message. The handle is well formed, so this is not a bad "
    + "argument. It is also not evidence that the message does not exist. Graph answers "
    + "'deleted', 'never existed', and 'the signed-in user cannot see it' with the same 404. "
    + "Graph does not say which of these it meant. Report that this tool did not read the "
    + "message, never that it was never written. Retrying will not help, and this connector has "
    + "no other route to the text. One well-formed handle always fails this way: a reply in a "
    + "channel thread is addressed under the post it answers. teams_list_message_replies reads the "
    + "replies of one post, but it needs the handle of the post that the reply answers. "
    + "teams_browse_channel reads the replies of each post on the channel's first page, and no "
    + "further. A search hit that is a reply does not name its post, so teams_browse_channel is "
    + "its only route. teams_browse_channel follows neither Microsoft's cursor into an older part "
    + "of a thread, nor the one into older posts. This is "
    + "because a given channel allows this whole connector about one request a second, across "
    + "the whole tenant. Browse that channel once. If the reply is not in what comes back, "
    + "there is no route to its full text, and a second browse returns the same window. Report "
    + "the search snippet with its sender and date. Say that this tool did not retrieve the "
    + "full text. Then stop looking."
)

_HANDLE_SOURCES = (
    "teams_search_messages, teams_browse_channel, teams_list_message_replies and "
    + "teams_list_chat_messages give a message handle."
)


async def teams_read_message(client: GraphServiceClient, *, handle: MessageHandle) -> TeamsMessage:
    with graph_errors(TOOL_NAME):
        message = await get_message(client, handle)

    assert message is not None, "Graph answered a message read with no message"
    return TeamsMessage.from_message(message, handle=handle)


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
                    "The message handle, as the `uri` of a message from teams_search_messages, "
                    + "teams_browse_channel, teams_list_message_replies, or "
                    + "teams_list_chat_messages. Copy it word for word."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage:
        handle = message_handle(uri)
        if handle is None:
            raise ToolError(not_a_message_handle(TOOL_NAME, _HANDLE_SOURCES))
        await narrowed_to(ctx, handle.permission)
        return await teams_read_message(client, handle=handle)
