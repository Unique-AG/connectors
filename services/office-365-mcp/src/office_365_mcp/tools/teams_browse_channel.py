"""`teams_browse_channel` — one Teams channel's posts with their newest replies.

TRAP: Graph orders by reply-chain last modified, so a two-year-old post moves to the first page
when someone replies to it. That order is kept, because re-sorting would invent an order Graph
never gave; read `created_at` to know when a post was written.

One request only: Graph rate-limits channel reads to one request per second for this app across
the tenant. The collection accepts only `$top` and `$expand=replies`, and Graph documents no
`$orderby` and no date filter for it.

The reply handle minted here follows `shared/handles.py`'s grammar, so `teams_read_message`
resolves it;
the shape is `shared/messages.py`'s, so a browsed post and a read message are one type.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.teams.item.channels.item.messages.messages_request_builder import (
    MessagesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.handles import CHANNEL_PERMISSION, MessageHandle
from office_365_mcp.shared.messages import MAX_REPLIES_PER_POST, TeamsMessage, event_of
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_browse_channel"

STEP = "channel_messages"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHANNEL_PERMISSION,)

# Invented ids, but a shape this tool accepts: an argument it rejects never reaches Graph.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "channel_id": "19:general@thread.tacv2",
}

# Graph's documented ceiling on `$top` for a channel's messages, and the most one request holds.
MAX_POSTS = 50

type _MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Read one Teams channel's posts in full. Use it for "what is in this channel", with `team_id` \
from teams_list_my_teams and `channel_id` from teams_list_channels; for a keyword, a person or any \
date bound, \
use teams_search_messages — there is no date filter here. One call is one request: raise \
`limit` rather than calling again. Microsoft orders by reply-chain activity, not post date: \
read `created_at` before trusting the order. Returns each post with its newest replies, whole.\
"""


class ChannelPosts(BaseModel):
    messages: list[TeamsMessage] = Field(
        description=(
            "Posts and their replies, in thread order. Each root post is followed by its replies, "
            + "oldest first. Replies carry `reply_to_id` with their parent post. Each message is "
            + "complete — same shape and text as `teams_read_message` returns — no second read "
            + "needed.\n"
            + "Up to `limit` posts returned (raise it, up to "
            + f"{MAX_POSTS}). Up to {MAX_REPLIES_PER_POST} newest replies per post; older ones "
            + "are unreachable and browsing again returns the same newest ones, so when a search "
            + "hit is a reply older than this window there is no route to its full text anywhere "
            + "in this connector — report the search snippet and stop looking. Fewer posts than "
            + "`limit` is NOT "
            + "proof the channel holds no more — Microsoft drops system messages after counting "
            + "them. Set `include_window_completeness` for `more_posts_in_channel` (the only way "
            + "to know if more exists). Microsoft orders by reply-chain last modified, not date; "
            + "use `teams_search_messages` with `sent_before` to reach back in time."
        )
    )
    more_posts_in_channel: bool | None = Field(
        description=(
            "Microsoft's cursor on the page (`@odata.nextLink`), or null if "
            + "`include_window_completeness` was not set (the default). True: more posts "
            + "exist beyond this page; a wider `limit` gets a little more, `teams_search_messages` "
            + "with `sent_before` reaches older posts. False: this window was the whole "
            + "channel (subject to `limit` and reply limits). Null means this field was not "
            + "requested. A short page alone does NOT mean the channel ran out."
        )
    )
    posts_cut_to_limit: bool | None = Field(
        description=(
            "Whether Microsoft's page held more posts than `limit` and this answer was cut "
            + "to it, or null if `include_window_completeness` was not set. Different from "
            + f"`more_posts_in_channel`: raise `limit` (up to {MAX_POSTS}) to get the cut "
            + "posts; they are in the next answer. Normally false because `$top` is set to "
            + "`limit`. Reported, not assumed, because the window is this tool's promise."
        )
    )


async def teams_browse_channel(
    client: GraphServiceClient,
    *,
    team_id: str,
    channel_id: str,
    limit: int,
    include_window_completeness: bool,
) -> ChannelPosts:
    """Up to `limit` posts from a channel's first page, each with its newest replies.

    One Graph request, always. Neither cursor is followed: not `@odata.nextLink` on the collection,
    not `replies@odata.nextLink` on a post. The reply window is deliberately not a third reported
    fact — older replies are unreachable either way, so nothing could act on it. See `_replies`.
    """
    assert 1 <= limit <= MAX_POSTS, f"limit must be within 1..{MAX_POSTS}, got {limit}"

    configuration = RequestConfiguration[_MessagesQuery](
        query_parameters=MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            expand=["replies"], top=limit
        )
    )
    with graph_errors(TOOL_NAME, step=STEP):
        page = await (
            client.teams.by_team_id(team_id)
            .channels.by_channel_id(channel_id)
            .messages.get(request_configuration=configuration)
        )
        assert page is not None, "Graph answered a channel message listing with no collection"

    # The window is this tool's promise, not Graph's: apply `limit` rather than trust `$top`.
    posts = [message for message in (page.value or []) if _is_a_post(message)]
    kept = posts[:limit]

    messages: list[TeamsMessage] = []
    for post in kept:
        assert post.id is not None, "Graph returned a channel message with no id"
        messages.append(
            TeamsMessage.from_message(
                post, handle=MessageHandle(post.id, team_id=team_id, channel_id=channel_id)
            )
        )
        messages.extend(
            TeamsMessage.from_message(
                reply,
                handle=MessageHandle(
                    _reply_id(reply), team_id=team_id, channel_id=channel_id, reply_to_id=post.id
                ),
            )
            for reply in _replies(post)
        )

    return ChannelPosts(
        messages=messages,
        more_posts_in_channel=bool(page.odata_next_link) if include_window_completeness else None,
        posts_cut_to_limit=len(kept) < len(posts) if include_window_completeness else None,
    )


def _is_a_post(message: ChatMessage) -> bool:
    return event_of(message) is None


def _replies(post: ChatMessage) -> list[ChatMessage]:
    """Newest `MAX_REPLIES_PER_POST` replies to `post`, oldest first.

    Sorted here because Graph does not order replies: the collection documents `$top` only. Graph
    expands up to 200 replies per post, so a thread it paged is past this window either way.
    """
    replies = sorted((reply for reply in post.replies or [] if _is_a_post(reply)), key=_sent_at)
    return replies[-MAX_REPLIES_PER_POST:]


def _sent_at(message: ChatMessage) -> datetime:
    return message.created_date_time or datetime.min.replace(tzinfo=UTC)


def _reply_id(reply: ChatMessage) -> str:
    assert reply.id is not None, "Graph returned a channel reply with no id"
    return reply.id


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    # Closes over `transport` here; the default below holds this name, not a call (ruff's B008).
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Browse a Teams Channel",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def browse_a_channel(
        team_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The team the channel is in, exactly as `teams_list_my_teams` reported. A "
                    + "channel id "
                    + "alone does not address a channel."
                ),
            ),
        ],
        channel_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The channel to read, exactly as `teams_list_channels` or "
                    + "`teams_search_messages` "
                    + "reported "
                    + "it. Opaque — copy it, do not build it from a channel name."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_POSTS,
                description=(
                    "How many posts to return, each with its replies. Default 20, maximum "
                    + f"{MAX_POSTS} (both Graph's own for this collection). One call is one "
                    + "request against the channel and is the whole of its window: raise "
                    + "`limit` to see more rather than calling again. Microsoft drops system "
                    + "messages after counting them, so a page can hold fewer posts than "
                    + "`limit`."
                ),
            ),
        ] = 20,
        include_window_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Report whether this window was the whole channel as `more_posts_in_channel` "
                    + "and `posts_cut_to_limit`. Off by default. Set it when the answer turns on "
                    + "completeness — this is the one tool where a short page tells you nothing. "
                    + "Microsoft counts system messages into the page before they are dropped. "
                    + "`more_posts_in_channel` is Microsoft's cursor: the channel holds more and "
                    + "nothing here reaches it. `posts_cut_to_limit` is the ordinary case of "
                    + "more posts on the page than `limit`, fixed by raising `limit`. Both "
                    + "are null when not requested."
                )
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> ChannelPosts:
        return await teams_browse_channel(
            client,
            team_id=team_id,
            channel_id=channel_id,
            limit=limit,
            include_window_completeness=include_window_completeness,
        )
