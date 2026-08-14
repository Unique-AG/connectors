"""The channel side of Microsoft Teams: a user's teams, a team's channels, one channel's posts.

`chats` and `message_search` reach the conversations a user is *in*; nothing so far reaches the
channels they can *browse*. Three Graph collections cover it, and each one is documented as
refusing something a caller would expect it to accept:

* `GET /me/joinedTeams` — "This method doesn't currently support the OData query parameters"
  (https://learn.microsoft.com/en-us/graph/api/user-list-joinedteams). No `$top`, no `$select`, no
  `$filter`, and no documented order. `services/teams-mcp` shipped a `$top` here and had to take it
  back out ("drop unsupported $top on joinedTeams and channels lists"), so it is not sent. Only
  `id`, `displayName`, `description`, `isArchived` and `tenantId` come back populated; every other
  property of a team is null on this endpoint whether or not it is asked for.
* `GET /teams/{id}/channels` — `$select` and `$filter` only, again no `$top`
  (https://learn.microsoft.com/en-us/graph/api/channel-list). `$select` is not an optimisation here
  but a requirement: Graph documents populating a channel's `email` as "an expensive operation that
  results in slow performance", and the only way not to pay for it is to select around it. The
  collection is already access-trimmed — "Teams members can't see private or shared channels that
  they aren't members of in the response for this API".
* `GET /teams/{id}/channels/{id}/messages` — `$top` (default 20, max 50) and `$expand=replies`, and
  nothing else: "The other OData query parameters aren't currently supported"
  (https://learn.microsoft.com/en-us/graph/api/channel-list-messages). **No `$filter` and no
  `$orderby`**, so this collection cannot be date-bounded at all and no date parameter is offered —
  `message_search` puts a date into the search index instead, for the price of the one request it
  was making anyway.

The last of those also has the ordering nobody expects. Graph sorts it "by the last modified date
of the entire reply chain, including both the root channel message and its replies", so a two-year-
old post returns to the first page the moment somebody replies to it. That is thread activity, not
post recency: it makes "the newest posts" the wrong reading of a page, and it makes "stop paging
once a page is older than X" an unsound stop condition — a walk down this collection could not know
when it had gone back far enough, which is one of the two reasons there is no walk (the other is
below).

Neither is there a sweep — of channels, or of a channel's own pages. Graph caps reads at "one
request per second per app per tenant … on a given channel"
(https://learn.microsoft.com/en-us/graph/throttling-limits) and that budget is per *app*, so
walking every channel of a team degrades every other user in the tenant, and following
`@odata.nextLink` down one channel spends the tenant's whole budget for that channel on one
caller. `browse_channel` therefore issues exactly one request: `$top` is the window and the single
page Graph answers with is the answer, which is why the answer is described as a window rather than
flagged as a partial one. A caller who needs a wider window raises `limit`; searching across
channels is `message_search`'s job.
"""

from datetime import UTC, datetime

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.channel import Channel
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.team import Team
from msgraph.generated.teams.item.channels.channels_request_builder import ChannelsRequestBuilder
from msgraph.generated.teams.item.channels.item.messages.messages_request_builder import (
    MessagesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.features.message_read import TeamsMessage, event_of, message_of
from office_mcp.features.message_search import CHANNEL_PERMISSION, MessageHandle
from office_mcp.graph_client import collect_pages, graph_errors

# One permission per request, as Graph documents them: listing teams and listing channels are the
# two cheap "basic" scopes, and reading what was posted in a channel is the broad one that also
# buys channel coverage in `message_search`. That last one is imported rather than repeated —
# `message_search` is where the permission constants live because that is where handles do, and a
# second spelling of `ChannelMessage.Read.All` is a second thing to keep true.
TEAMS_PERMISSION = "Team.ReadBasic.All"
CHANNELS_PERMISSION = "Channel.ReadBasic.All"
POSTS_PERMISSION = CHANNEL_PERMISSION

# Neither inventory collection takes a `$top`, so a window over them is this connector's own and so
# is its bound. It exists to cap the number of Graph requests one call can make, not because Graph
# would refuse a larger one.
MAX_LISTED = 200

# Graph's documented ceiling on `$top` for a channel's messages, and so the widest window one
# `browse_channel` call can answer with: the call is one request and `$top` is the whole of it.
MAX_POSTS = 50

# How many of a post's replies are returned. `$expand=replies` brings back up to 200 replies per
# post, and 50 posts of 200 replies is a response no caller has a budget for — so the newest of
# each thread are kept, and a thread that came back full to this window is one that may have older
# replies, exactly as a full page is elsewhere here.
#
# This window is the end of the line rather than a first page. Graph puts its own cursor on a post
# whose expanded replies were themselves paged, and following it is a request per post against a
# channel that allows the whole app one a second — the same reason the channel's own pages are not
# walked. That cursor needs no separate reporting: Graph expands up to 200 replies before it pages
# them, so a thread it paged has far more than this window holds and the window comes back full. So
# a reply older than this window has no route to its full text here: `message_search` can find it
# and report Microsoft's snippet, but Graph addresses a reply under the post it answers and the
# search index does not name that post, so such a hit cannot be read. Browsing again returns the
# same newest replies, which is why every surface that mentions this says so rather than sending a
# caller back round.
MAX_REPLIES_PER_POST = 10

# What a channel listing asks for, which is everything Graph populates that identifies a channel.
# `email` is excluded deliberately (see the module docstring), and so is `isArchived`: Graph
# documents `layoutType` as coming back null on this collection and archived channels are a Teams
# preview concept, so neither is claimed here.
_CHANNEL_FIELDS = ("id", "displayName", "description", "createdDateTime", "membershipType")

type _ChannelsQuery = ChannelsRequestBuilder.ChannelsRequestBuilderGetQueryParameters
type _MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters


class TeamSummary(BaseModel):
    team_id: str = Field(
        description=(
            "The team's Graph id. It is what list_channels and browse_channel take, and the same "
            + "id search_messages reports as `team_id` on a channel message. Opaque — copy it, "
            + "never build one from a team's name."
        )
    )
    display_name: str | None = Field(
        description="The team's name as Teams shows it. Two teams may share one."
    )
    description: str | None = Field(
        description=(
            "What the team is for, as its owners wrote it. Null when nobody wrote one, which is "
            + "common."
        )
    )
    is_archived: bool | None = Field(
        description=(
            "True for a team that has been archived, which in Teams means read-only and usually "
            + "means finished. Null when Microsoft Graph did not say. Together with `description` "
            + "this is what tells two teams with the same name apart."
        )
    )


class TeamList(BaseModel):
    teams: list[TeamSummary] = Field(
        description=(
            "The teams the signed-in user is a member of. As many as `limit` means there may be "
            + "more; fewer than `limit` is all of them, because the walk follows Microsoft's "
            + "paging to the end of the collection. There is no cursor: raise `limit` (up to "
            + f"{MAX_LISTED}) to widen the window. Microsoft Graph applies no order here, so the "
            + "teams beyond a full window are an arbitrary rest rather than the least important "
            + "ones."
        )
    )


class ChannelSummary(BaseModel):
    channel_id: str = Field(
        description=(
            "The channel's Graph id, e.g. `19:...@thread.tacv2`. Pass it with its `team_id` to "
            + "browse_channel; it is also the id search_messages reports as `channel_id` on a "
            + "channel message. Opaque — copy it rather than constructing one from a name."
        )
    )
    display_name: str | None = Field(
        description=(
            "The channel's name as Teams shows it, e.g. `General`. Every team has a `General` "
            + "channel, so a name is only unique within its own team."
        )
    )
    description: str | None = Field(
        description="What the channel is for, as its owners wrote it. Often null."
    )
    membership_type: str | None = Field(
        description=(
            "`standard` for a channel every team member is in, `private` for one with its own "
            + "member list, or `shared` for one shared with other teams. Null when Microsoft Graph "
            + "reported a type this connector predates. Private and shared channels the signed-in "
            + "user is not a member of are not in this list at all."
        )
    )
    created_at: datetime | None = Field(
        description="When the channel was created — useful to tell apart similarly named channels."
    )


class ChannelList(BaseModel):
    channels: list[ChannelSummary] = Field(
        description=(
            "The channels of this team that the signed-in user can see. As many as `limit` means "
            + "there may be more; fewer than `limit` is all of them the user can see. There is no "
            + f"cursor: raise `limit` (up to {MAX_LISTED}). Microsoft Graph applies no order to "
            + "this collection either."
        )
    )


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
            + "the same is true of a thread's replies. There is no cursor and paging deeper is "
            + "not a route to older posts: Microsoft orders this collection by reply-chain "
            + "activity rather than by date, so reaching back in time is search_messages with "
            + "`sent_before`."
        )
    )


async def list_teams(client: GraphServiceClient, *, limit: int) -> TeamList:
    """The teams the signed-in user is a member of, up to `limit`.

    No request configuration at all: `/me/joinedTeams` accepts no OData query parameters, so a
    `$top` or a `$select` here is a 400 rather than a narrower answer. The window is therefore
    applied while walking the pages Graph chose.
    """
    assert 1 <= limit <= MAX_LISTED, f"limit must be within 1..{MAX_LISTED}, got {limit}"

    with graph_errors():
        first_page = await client.me.joined_teams.get()
        assert first_page is not None, "Graph answered GET /me/joinedTeams with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return TeamList(teams=[_team(team) for team in collected.items])


def _team(team: Team) -> TeamSummary:
    assert team.id is not None, "Graph returned a joined team with no id"
    return TeamSummary(
        team_id=team.id,
        display_name=team.display_name,
        description=team.description,
        is_archived=team.is_archived,
    )


async def list_channels(client: GraphServiceClient, *, team_id: str, limit: int) -> ChannelList:
    """The channels of `team_id` the signed-in user can see, up to `limit`."""
    assert 1 <= limit <= MAX_LISTED, f"limit must be within 1..{MAX_LISTED}, got {limit}"

    configuration = RequestConfiguration[_ChannelsQuery](
        query_parameters=ChannelsRequestBuilder.ChannelsRequestBuilderGetQueryParameters(
            select=list(_CHANNEL_FIELDS)
        )
    )
    with graph_errors():
        first_page = await client.teams.by_team_id(team_id).channels.get(
            request_configuration=configuration
        )
        assert first_page is not None, "Graph answered a channel listing with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return ChannelList(channels=[_channel(channel) for channel in collected.items])


def _channel(channel: Channel) -> ChannelSummary:
    assert channel.id is not None, "Graph returned a channel with no id"
    # `ChannelMembershipType` subclasses `str`, so the member is its own wire value ("standard");
    # a value the generated enum has no member for deserializes to None rather than raising.
    return ChannelSummary(
        channel_id=channel.id,
        display_name=channel.display_name,
        description=channel.description,
        membership_type=channel.membership_type,
        created_at=channel.created_date_time,
    )


async def browse_channel(
    client: GraphServiceClient, *, team_id: str, channel_id: str, limit: int
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
    Graph counted them into: a page can hold fewer posts than `limit` without the channel having
    run out of them. There is no flag saying so, because there is nothing a caller would do
    differently — this call is one window either way and `ChannelPosts.messages` says so — and a
    flag whose two causes have no remedy between them is a caveat, not a signal.
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

    messages: list[TeamsMessage] = []
    for post in posts[:limit]:
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

    return ChannelPosts(messages=messages)


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
