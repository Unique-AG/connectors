"""`browse_channel` — one Teams channel's posts, each followed by the replies to it.

The one thing the other message tools cannot do: walk a single channel. `search_messages` finds
messages by keyword across every chat and channel at once and cannot be scoped to one of them;
`read_message` reads a message somebody already has a handle for. This is the tool for "what is
going on in this channel".

Four things make it what it is, and each of them is a decision rather than a detail.

**The order is thread activity, not post recency.** Graph sorts this collection "by the last
modified date of the entire reply chain, including both the root channel message and its replies"
(https://learn.microsoft.com/en-us/graph/api/channel-list-messages), so a two-year-old post returns
to the first page the moment somebody replies to it. That order is preserved rather than corrected —
reordering it would be inventing an order Graph did not give — and `created_at` is what tells the
truth about age. It also makes "stop paging once a page is older than X" an unsound stop condition:
a walk down this collection could not know when it had gone back far enough, which is one of the two
reasons there is no walk.

**There is no sweep, and that is the other reason.** Graph caps reads at "one request per second per
app per tenant … on a given channel" (https://learn.microsoft.com/en-us/graph/throttling-limits),
and that budget is per *app* — so walking every channel of a team degrades every other user in the
tenant, and following `@odata.nextLink` down one channel spends the tenant's whole budget for that
channel on one caller. This tool therefore issues exactly one request: `$top` is the window and the
single page Graph answers with is the answer. A caller who needs a wider window raises `limit`;
searching across channels is `search_messages`'s job.

**It cannot be date-bounded at all.** `$top` and `$expand=replies` are the only parameters this
collection takes — "The other OData query parameters aren't currently supported" — so there is no
`$filter` and no `$orderby`, and no date parameter is offered rather than one being faked.
`search_messages` puts a date into the search index instead, for the price of the one request it was
making anyway.

**That one page is the one place here where "was that everything?" is not derivable.** Everywhere
else a page short of `limit` is the end of the collection, because the walk underneath followed
Graph's paging to it; here nothing is followed, and system messages are dropped out of the page
after Graph counted them into it, so a short answer says nothing either way. What does say something
is Graph's own `@odata.nextLink` on that page — an accurate read, and the only one available — so it
is reported, opt-in, as `ChannelPosts` explains.

What this file does not own is the handle grammar (`shared/handles.py`, so that the reply handle
this mints is the one `read_message` resolves — and this is the only tool that can mint it, because
Graph addresses a reply under the post it answers and a search projection carries no `replyToId`),
the message shape and its Teams-HTML normaliser, which also holds the reply window
(`shared/messages.py`, so that a post browsed here and a message read by handle are the same thing
rather than two that agree, and so that `read_message`'s 404 advice names the same number this
window is), and the token and refusal wording (`shared/seam.py`). Everything else — the name, the
description, the permission, the arguments, the answer shape and the request — is here.
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

# The one delegated permission this tool's one request needs: the broad message permission, which is
# also what buys `search_messages` its channel coverage. It is imported rather than respelled —
# which surface a Teams message is read under is handle vocabulary, and a second spelling of
# `ChannelMessage.Read.All` is a second thing to keep true. Several tools declaring one permission
# is what the registry's deduplication is for, and none of them may leave it out.
GRAPH_PERMISSIONS: tuple[str, ...] = (CHANNEL_PERMISSION,)

# Built once at import: a call inside a parameter default rebuilds the descriptor on every
# registration and is a lint error in both of this repo's checkers.
_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

# Graph's documented ceiling on `$top` for a channel's messages, and so the widest window one call
# can answer with: the call is one request and `$top` is the whole of it.
MAX_POSTS = 50

type _MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_DESCRIPTION = f"""\
Read what was posted in one Microsoft Teams channel: its posts with their full text, each followed \
by the replies to it. Takes the `team_id` and `channel_id` list_teams and list_channels returned.

This is the one thing the other message tools cannot do — walk a single channel in order. \
search_messages finds messages by keyword across every chat and channel at once but cannot be \
scoped to one channel, and read_message reads a single message you already have a handle for. \
Reach for this when the question is "what is going on in this channel" rather than "where was this \
mentioned". Do not call it for channel after channel: Microsoft rate-limits reads of a given \
channel to about one request a second for this whole connector across the tenant, so a sweep is \
slow for you and harmful to everyone else on it — search_messages covers every channel in one \
request. This call spends exactly one request of that budget: it reads the single page Microsoft \
answers with and never pages deeper, so `limit` is the whole window and widening `limit` — not \
calling again — is how to see more.

**The order is not what it looks like.** Microsoft sorts this collection by the last modified time \
of the entire reply chain, so a two-year-old post returns to the front the moment somebody replies \
to it. The first message here is the most recently *active* thread, not the most recent post. Read \
`created_at` before saying when anything was written, never the position in this list, and do not \
report the top of the list as "the latest news in the channel".

It cannot be date-filtered, and this is Microsoft's limit rather than a missing parameter: this \
collection accepts no filter and no sort at all. To bound by date use search_messages with \
`sent_after`/`sent_before`, which the search index applies and which covers channels. For the same \
reason, paging deeper is not a way to reach older posts — there is no cursor, and a wider `limit` \
(up to {MAX_POSTS}, Microsoft's own maximum) or a search is the only way to see more.

**Never report this as the whole of a channel unless you asked and were told.** A page holding \
fewer than `limit` posts is not evidence that the channel has no more — Microsoft counts the \
system messages into that page before they are dropped here — so, unlike every other list here, \
what comes back cannot tell you whether it was everything. Microsoft's page does say, and \
`include_window_completeness` is how to have it reported: `more_posts_in_channel` is Microsoft's \
own "there is more of this channel", which no `limit` here reaches — the older posts of a busy \
channel are reached by searching, not by asking again — and `posts_cut_to_limit` is the separate \
case of this window closing over posts Microsoft did send, which a wider `limit` does fix. Both \
are null unless you set it.

Replies come with their posts: up to {MAX_REPLIES_PER_POST} of the newest per post, \
oldest first, each carrying the post it answers in `reply_to_id`. A post carrying that many \
replies may have older ones, and those are out of reach rather than one call \
away — Microsoft's cursor into a thread is a request per post against the same one-a-second \
budget, so it is not followed and browsing again returns the same newest replies. Every message is \
complete — the same fields, and the same plain text normalised out of Teams' HTML, that \
read_message returns — so a message here needs no second call to read it. Its `uri` is a handle \
for quoting or re-reading it, and for a reply it is the only handle that exists: Microsoft \
addresses a reply under its parent post, which a search result cannot express. That is also the \
limit of what this tool can rescue: when a search hit is a reply older than the window above, \
there is no route to its full text anywhere in this connector — report the search snippet, say so, \
and do not browse again for it.

System messages are dropped — somebody joining, a call ending, a channel being renamed — because \
Microsoft gives them no author and no text. That is why a page can hold fewer posts than `limit`, \
and it is not evidence that the channel is quiet.\
"""


class ChannelPosts(BaseModel):
    messages: list[TeamsMessage] = Field(
        description=(
            "The channel's posts and their replies, in thread order: each root post is followed by "
            + "the replies to it, oldest first, and a reply carries the post it answers in "
            + "`reply_to_id`. Every message is complete — the same shape and the same normalised "
            + "text read_message answers with — so nothing here needs a second read.\n"
            + "This is one window on the channel and never the whole of it, whatever comes back. "
            + f"Up to `limit` posts are returned (raise it, up to {MAX_POSTS}) and up to "
            + f"{MAX_REPLIES_PER_POST} of the newest replies per post, so a post carrying that "
            + "many replies may have older ones — and those are a dead end rather than a next "
            + "page, because browsing again returns the same newest ones. FEWER posts than "
            + "`limit` is NOT evidence that the channel holds no more: Microsoft counts system "
            + "messages into the page it answers with and they are dropped from this list, and "
            + "the same is true of a thread's replies. Whether the channel does hold more is the "
            + "one thing here you cannot read off this list, and Microsoft's own answer to it is "
            + "reported when you ask: set `include_window_completeness` for "
            + "`more_posts_in_channel`. There is no cursor and paging deeper is not a route to "
            + "older posts: Microsoft orders this collection by reply-chain activity rather than "
            + "by date, so reaching back in time is search_messages with `sent_before`."
        )
    )
    more_posts_in_channel: bool | None = Field(
        description=(
            "Whether Microsoft said this channel holds posts beyond the page it answered with — "
            + "its `@odata.nextLink` on that page, reported as it came — or null when "
            + "`include_window_completeness` was not set, which is the default.\n"
            + "True means there ARE more posts and this window is not the channel. It is not a "
            + "cursor and there is nothing here to page with: this tool spends one request against "
            + "a channel Microsoft rate-limits to about one a second for the whole connector, so "
            + "the remedy is a wider `limit` for a little more, and search_messages with "
            + "`sent_before` to reach back in time. False means Microsoft offered no continuation "
            + f"of the collection, so — subject to `limit` and to {MAX_REPLIES_PER_POST} replies a "
            + "post — this window was the whole channel. This is the only thing that says either "
            + "way: a short list does NOT mean the channel ran out."
        )
    )
    posts_cut_to_limit: bool | None = Field(
        description=(
            "Whether Microsoft's page held more posts than `limit` and this answer was cut to it, "
            + "or null when `include_window_completeness` was not set. A different fact from "
            + f"`more_posts_in_channel` with a different remedy: raise `limit` (up to {MAX_POSTS}) "
            + "and the cut posts are in the next answer, where more of the channel is not "
            + "reachable at all. Normally false whatever the channel holds — `$top` is set to "
            + "`limit`, so Microsoft answers with no more than that — and reported rather than "
            + "assumed because the window is this tool's promise rather than Microsoft's."
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
    """Up to `limit` posts from one channel's first page, each with the newest of its replies.

    One Graph request against the channel, always. Graph's per-channel budget is a single request a
    second for the whole app in the tenant, so neither cursor Graph offers here is followed: not the
    collection's `@odata.nextLink` and not a post's own `replies@odata.nextLink`. `$top` is the
    window and `$expand=replies` makes a thread part of that one request rather than a round trip
    per post; a caller who needs more raises `limit` (up to `MAX_POSTS`, Graph's own ceiling)
    instead of the tool spending the tenant's budget on their behalf.

    The system messages — somebody joining, a call ending, a channel being renamed — are dropped,
    and Graph offers no `$filter` to drop them at the source, so they are filtered out of the page
    Graph counted them into: a page can hold fewer posts than `limit` without the channel having run
    out of them. That is what makes this the one tool here whose answer cannot say whether it was
    everything, and the reason `include_window_completeness` exists at all. Elsewhere a short
    answer is the end of the collection — `collect_pages` followed Graph's paging to it — so "there
    is more" is derivable and is not reported; here nothing was followed and a short answer says
    nothing.

    Two facts are reported for it, separately, because their remedies are opposite ones and one
    boolean over both is the ambiguous "there is more" flag no answer here carries — it would mean
    "raise `limit`" or "nothing will help" with no way to tell which. `more_posts_in_channel` is
    Graph's own `@odata.nextLink` on the page, read as it came: the channel holds more, and nothing
    here reaches it — a wider `limit` buys a little more of the same page and `search_messages` is
    the route back in time. `posts_cut_to_limit` is this function's own window closing over posts
    Graph did send, which a wider `limit` does fix. Both are null unless asked for: a field that is
    null for almost every answer is one a model need not reason about, and only a caller whose
    question turns on it pays that price.

    The reply window is deliberately not a third fact here. A thread's older replies are out of
    reach whether or not Graph paged them, so nothing acts on it — see `_replies`.
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

    # `$top` is `limit`, so Graph returning more posts than were asked for should not happen — but
    # the window is this tool's promise rather than Graph's, so it is applied rather than trusted.
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
    """The newest `MAX_REPLIES_PER_POST` replies to `post`, oldest first.

    Sorted here because Graph publishes no order for replies — the reply collection documents
    `$top` and nothing else — so the order they arrive in is not a contract to preserve. The newest
    are the ones kept: a thread's recent turns are what a question about it is usually about.

    Whether older ones were left behind is not reported, because a full window says it: Graph
    expands up to 200 replies per post, so a thread it paged had more than 200 of them and the
    window returned is full either way. That leaves the same reading as everywhere else here — this
    many replies means there may be more, fewer means that was the thread.
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
                    "The team the channel belongs to, exactly as list_teams reported its "
                    + "`team_id`. A channel id alone does not address a channel."
                ),
            ),
        ],
        channel_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The channel to read, exactly as list_channels reported its `channel_id` (or "
                    + "as search_messages reported `channel_id` on a channel message). Opaque — a "
                    + "channel's name is not one."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_POSTS,
                description=(
                    "How many posts to return, each with its replies. Default 20 and maximum "
                    + f"{MAX_POSTS} — both Microsoft Graph's own, for this collection. "
                    + "One call is one request against the channel and this is the whole of its "
                    + "window: widen it to see more rather than calling again. System messages are "
                    + "dropped after Graph counts them, so a page can hold fewer posts than this."
                ),
            ),
        ] = 20,
        include_window_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Report whether this window was the whole channel, as `more_posts_in_channel` "
                    + "and `posts_cut_to_limit` in the answer. Off by default; set it when the "
                    + "answer turns on completeness, because this is the one tool here where a "
                    + "short answer tells you nothing — it reads a single page, and Microsoft "
                    + "counts system messages into that page before they are dropped. "
                    + "`more_posts_in_channel` is Microsoft's own cursor on that page: the channel "
                    + "holds more, and nothing here pages to it. `posts_cut_to_limit` is the "
                    + "separate, ordinary case of more posts on the page than `limit`, which a "
                    + "wider `limit` fixes. Both are null when this is not set."
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
