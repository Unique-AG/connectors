"""`browse_channel` — one Teams channel's posts with their newest replies.

Walk one channel — the only message tool that can. `search_messages` finds messages by keyword
across every chat and channel, not one. `read_message` reads a message by handle.

Four design decisions:

**Order is thread activity, not post date.** Graph sorts by reply-chain last modified, so a
two-year-old post moves to the first page when someone replies to it. This order is preserved.
Read `created_at` to know when a post was written, not its position here.

**One request only.** Graph rate-limits channel reads to one request per second for this app
across the tenant. This tool makes one request: `$top` is the window, the single page Graph
answers with is the result.

**No date filter.** This collection accepts only `$top` and `$expand=replies`, no `$filter`.
Use `search_messages` with `sent_after`/`sent_before` to search by date.

**Cannot tell if a page is the whole channel.** System messages are dropped after Graph counts them,
so a short page is not proof the channel is empty. Graph's `@odata.nextLink` on the page says if
more exists — reported via `include_window_completeness`.

This file owns the name, description, permission, arguments, answer shape and request. The handle
grammar lives in `shared/handles.py` (so the reply handle this tool mints is what `read_message`
resolves and this is the only tool that can mint it). The message shape and Teams HTML normaliser
live in `shared/messages.py` (so a post browsed and a message read are the same type). Token and
error text live in `shared/seam.py`.
"""

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

from office_mcp.graph_client import graph_client_for, graph_errors
from office_mcp.shared.handles import CHANNEL_PERMISSION, MessageHandle
from office_mcp.shared.messages import (
    MAX_REPLIES_PER_POST,
    TeamsMessage,
    event_of,
    message_of,
)
from office_mcp.shared.seam import READ_ONLY, graph_token, graph_tool_errors

TOOL_NAME = "browse_channel"

# Import CHANNEL_PERMISSION to avoid misspelling — handle vocabulary owns surface permissions.
# Several tools declare one permission; deduplication is the registry's job.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHANNEL_PERMISSION,)

# Built at import time. A parameter default call rebuilds the descriptor on every registration.
_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

# Graph's documented ceiling on `$top` for a channel's messages — the whole of one request.
MAX_POSTS = 50

type _MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_DESCRIPTION = f"""\
Read a Teams channel's posts with their replies. Take `team_id` and `channel_id` from list_teams \
and list_channels.

This is the only message tool that walks one channel. `search_messages` finds messages by keyword \
across channels and chats (not scoped to one). `read_message` reads a single message by handle. \
Use this when you need to know "what is in this channel".

**Do not sweep channels.** Microsoft rate-limits a given channel to about one request per second \
for this app across the tenant. This tool makes one request: `$top` is the window. To see more, \
raise `limit` rather than calling again. `search_messages` covers all channels in one request.

**The order is thread activity, not post date.** Microsoft sorts by the last-modified time of the \
entire reply chain. A two-year-old post moves to the first page when someone replies to it. Read \
`created_at` to know when a post was written — not its position here or the top of the list.

**Cannot filter by date.** This collection accepts only `$top` and `$expand=replies`. Use \
`search_messages` with `sent_after`/`sent_before` for date bounds.

**Cannot tell if a page is the whole channel.** Microsoft drops system messages after counting \
them, so a short page is not proof the channel is empty. Set `include_window_completeness` to see \
Microsoft's cursor on the page (`more_posts_in_channel`) — the only accurate answer.

Replies come with posts: up to {MAX_REPLIES_PER_POST} newest per post, oldest first. Each reply \
carries `reply_to_id` with its parent. Older replies on a post are unreachable — browsing again \
returns the same newest ones. Every message is complete (same shape and text as `read_message` \
returns). A reply's `uri` is its only handle, because Microsoft addresses it under its parent — \
search cannot express this. When a search hit is a reply older than this window, there is no \
route to its full text anywhere in this connector — report the search snippet and stop looking.

System messages (joins, call ends, renames) are dropped — Microsoft gives them no author or text. \
That is why pages may be shorter than `limit` and is not evidence the channel is quiet.\
"""


class ChannelPosts(BaseModel):
    messages: list[TeamsMessage] = Field(
        description=(
            "Posts and their replies, in thread order. Each root post is followed by its replies, "
            + "oldest first. Replies carry `reply_to_id` with their parent post. Each message is "
            + "complete — same shape and text as `read_message` returns — no second read needed.\n"
            + "Up to `limit` posts returned (raise it, up to "
            + f"{MAX_POSTS}). Up to {MAX_REPLIES_PER_POST} newest replies per post (older ones "
            + "unreachable, browsing returns the same newest). Fewer posts than `limit` is NOT "
            + "proof the channel holds no more — Microsoft drops system messages after counting "
            + "them. Set `include_window_completeness` for `more_posts_in_channel` (the only way "
            + "to know if more exists). Microsoft orders by reply-chain last modified, not date; "
            + "use `search_messages` with `sent_before` to reach back in time."
        )
    )
    more_posts_in_channel: bool | None = Field(
        description=(
            "Microsoft's cursor on the page (`@odata.nextLink`), or null if "
            + "`include_window_completeness` was not set (the default). True: more posts "
            + "exist beyond this page; a wider `limit` gets a little more, `search_messages` "
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


async def browse_channel(
    client: GraphServiceClient,
    *,
    team_id: str,
    channel_id: str,
    limit: int,
    include_window_completeness: bool,
) -> ChannelPosts:
    """Return up to `limit` posts from a channel's first page, each with its newest replies.

    One Graph request, always. Graph rate-limits a given channel to one request per second for this
    app across the tenant. Neither cursor is followed: not `@odata.nextLink` on the collection or
    `replies@odata.nextLink` on a post. `$top=limit` is the window; `$expand=replies` brings
    threads into one request instead of one per post. A caller who needs more raises `limit`
    instead of this tool spending the tenant's budget.

    System messages (joins, call ends, renames) are dropped. Graph has no `$filter` to drop them
    at the source, so they are filtered out of the page Graph counted them into. This means a page
    can be shorter than `limit` without the channel being empty. This is the one tool whose answer
    cannot say if it is everything — that is why `include_window_completeness` exists. Elsewhere
    a short answer means the end of the collection (paging reached it); here nothing was followed,
    so a short answer says nothing.

    Two facts are reported separately because their remedies differ and one boolean over both would
    be ambiguous. `more_posts_in_channel`: Graph's `@odata.nextLink` as-is. The channel holds more,
    and nothing here reaches it — raise `limit` for more of the same page, `search_messages` for
    older posts. `posts_cut_to_limit`: this function's window closing over posts Graph did send;
    raise `limit` to get them. Both are null unless asked for.

    Reply window is deliberately not a third fact. Older replies on a post are unreachable either
    way, so nothing acts on it — see `_replies` function.
    """
    assert 1 <= limit <= MAX_POSTS, f"limit must be within 1..{MAX_POSTS}, got {limit}"

    configuration = RequestConfiguration[_MessagesQuery](
        query_parameters=MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            expand=["replies"], top=limit
        )
    )
    with graph_errors():
        page = await (
            client.teams.by_team_id(team_id)
            .channels.by_channel_id(channel_id)
            .messages.get(request_configuration=configuration)
        )
        assert page is not None, "Graph answered a channel message listing with no collection"

    # The window is this tool's promise, not Graph's, so apply it rather than trust it.
    posts = [message for message in (page.value or []) if _is_a_post(message)]
    kept = posts[:limit]

    messages: list[TeamsMessage] = []
    for post in kept:
        assert post.id is not None, "Graph returned a channel message with no id"
        messages.append(
            message_of(post, handle=MessageHandle(post.id, team_id=team_id, channel_id=channel_id))
        )
        messages.extend(
            message_of(
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
    """Whether a person wrote this, rather than Teams recording that something happened."""
    return event_of(message) is None


def _replies(post: ChatMessage) -> list[ChatMessage]:
    """Newest `MAX_REPLIES_PER_POST` replies to `post`, oldest first.

    Sorted here because Graph does not order replies — the reply collection documents `$top`
    only, so the arrival order is not a contract to preserve. Keep the newest: a thread's recent
    turns are usually what a question needs. Whether older replies were left behind is not
    reported, because a full window already says it: Graph expands up to 200 replies per post, so
    a thread it paged had more than 200 and the window is full either way. That leaves the same
    reading as everywhere here: this many replies means there may be more, fewer means that was
    the thread.
    """
    replies = sorted((reply for reply in post.replies or [] if _is_a_post(reply)), key=_sent_at)
    return replies[-MAX_REPLIES_PER_POST:]


def _sent_at(message: ChatMessage) -> datetime:
    """When a message was sent, or the beginning of time for one Graph gave no timestamp."""
    return message.created_date_time or datetime.min.replace(tzinfo=UTC)


def _reply_id(reply: ChatMessage) -> str:
    assert reply.id is not None, "Graph returned a channel reply with no id"
    return reply.id


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this tool against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tool
    borrows it per call and never owns it. `create_app` closes it on shutdown.
    """

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
                    "The team the channel is in, exactly as `list_teams` reported. A channel id "
                    + "alone does not address a channel."
                ),
            ),
        ],
        channel_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The channel to read, exactly as `list_channels` or `search_messages` reported "
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
        graph_token: str = _TOKEN,
    ) -> ChannelPosts:
        with graph_tool_errors(*GRAPH_PERMISSIONS):
            return await browse_channel(
                graph_client_for(transport, graph_token),
                team_id=team_id,
                channel_id=channel_id,
                limit=limit,
                include_window_completeness=include_window_completeness,
            )
