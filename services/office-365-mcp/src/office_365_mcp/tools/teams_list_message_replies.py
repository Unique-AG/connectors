from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.teams.item.channels.item.messages.item.replies.replies_request_builder import (  # noqa: E501
    RepliesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.handles import CHANNEL_PERMISSION, MessageHandle, message_handle
from office_365_mcp.shared.messages import TeamsMessage, event_of, unknown_enum_headers
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_list_message_replies"

STEP = "channel_replies"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHANNEL_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": (
        "teams:///teams/2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
        + "/channels/19%3Ageneral%40thread.tacv2/messages/1770000000000"
    )
}

MAX_REPLIES = 50

type _RepliesQuery = RepliesRequestBuilder.RepliesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the replies to one Teams channel post, oldest first, as the signed-in user, by the `uri` of \
that post. Each reply has its own `uri`, which teams_read_message accepts. teams_browse_channel is \
the sibling tool that reads a page of posts with their replies.

Notes:
- One call is one request, because a given channel allows this whole connector about one request a \
second, across the whole tenant.
- This tool never follows Microsoft's cursor and reads at most 50 replies. If `more_replies` is \
true, the list is not the whole thread. Microsoft does not say which replies the list leaves out.\
"""

_NOT_A_POST_HANDLE = """\
teams_list_message_replies takes the `uri` handle of one channel post, and this value is not one. \
A post handle has exactly this shape:
  teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}
The ids are percent-encoded. teams_browse_channel and teams_search_messages give the handle of a \
post. A chat handle is not a post handle. A reply handle ends in `/replies/{reply_id}` and is not \
a post handle either. Copy the `uri` of a post word for word. If you call this tool again with \
this value, the call will fail the same way."""


class ThreadReplies(BaseModel):
    messages: list[TeamsMessage] = Field(
        description=(
            "The replies to the post, oldest first, without system events. Each `uri` is a reply "
            + "handle that teams_read_message reads. The post itself is not in this list."
        )
    )
    more_replies: bool = Field(
        description=(
            "True when Microsoft reported more replies than this call returned. False means that "
            + "this list holds every reply. This tool makes one request and never follows "
            + f"Microsoft's cursor, so it cannot read past {MAX_REPLIES} replies."
        )
    )


async def teams_list_message_replies(
    client: GraphServiceClient, *, uri: str, limit: int
) -> ThreadReplies:
    assert 1 <= limit <= MAX_REPLIES, f"limit must be within 1..{MAX_REPLIES}, got {limit}"
    post = message_handle(uri)
    if post is None or post.chat_id is not None or post.reply_to_id is not None:
        raise ToolError(_NOT_A_POST_HANDLE)
    assert post.team_id is not None and post.channel_id is not None, (
        "a channel post handle addresses a team channel"
    )

    configuration = RequestConfiguration[_RepliesQuery](
        headers=unknown_enum_headers(),
        query_parameters=RepliesRequestBuilder.RepliesRequestBuilderGetQueryParameters(top=limit),
    )
    with graph_errors(TOOL_NAME, step=STEP):
        page = await (
            client.teams.by_team_id(post.team_id)
            .channels.by_channel_id(post.channel_id)
            .messages.by_chat_message_id(post.message_id)
            .replies.get(request_configuration=configuration)
        )
        assert page is not None, "Graph answered a reply listing with no collection"

    replies = sorted((reply for reply in page.value or [] if event_of(reply) is None), key=_sent_at)
    return ThreadReplies(
        messages=[
            TeamsMessage.from_message(reply, handle=_reply_handle(post, reply)) for reply in replies
        ],
        more_replies=bool(page.odata_next_link),
    )


def _reply_handle(post: MessageHandle, reply: ChatMessage) -> MessageHandle:
    assert reply.id is not None, "Graph returned a channel reply with no id"
    return replace(post, message_id=reply.id, reply_to_id=post.message_id)


def _sent_at(message: ChatMessage) -> datetime:
    return message.created_date_time or datetime.min.replace(tzinfo=UTC)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List the Replies to a Teams Post",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def list_replies(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The channel post to read, as the `uri` of a teams_browse_channel or "
                    + "teams_search_messages message. Copy it word for word. A chat handle and a "
                    + "reply handle are not valid here."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_REPLIES,
                description=(
                    f"How many replies to request from Microsoft, at most {MAX_REPLIES}. This "
                    + "tool drops system events after the request, so the list can be shorter."
                ),
            ),
        ] = 20,
        client: GraphServiceClient = graph,
    ) -> ThreadReplies:
        return await teams_list_message_replies(client, uri=uri, limit=limit)
