"""`list_channels` — channels of one team the signed-in user can access.

`list_teams` names a team; this names a channel inside it. A channel id alone identifies nothing
in Graph. Channel names are unique only inside their own team — every team has a `General`.
Channel identification needs both ids.

**`$select` is a requirement: the connector must exclude the expensive `email` property.** Graph \
documents email as "an expensive operation that results in slow performance". Without `$select`, \
every channel listing pays that cost. The collection accepts no `$top` (Graph returns 400); \
the window is this connector's own, applied while walking pages.

Graph filters membership-based channels: private and shared channels the user is not a member of \
do not appear. An absent channel does not mean the team lacks it — only that the user cannot \
access it.

Token exchange and error wording belong to `shared/seam.py`; the tool owns the request, window,
answer shape, fields, permission, and description."""

from datetime import datetime
from typing import Annotated

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.channel import Channel
from msgraph.generated.teams.item.channels.channels_request_builder import ChannelsRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import collect_pages, graph_errors
from office_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "list_channels"

# The delegated Graph permission this tool's one request needs — the cheap "basic" scope over a
# channel's identity, which is all this collection returns. Reading what was *posted* in a channel
# is the broad `ChannelMessage.Read.All` and is `browse_channel`'s to declare; a tenant commonly
# grants this one and withholds that one, which is why the two are named separately.
GRAPH_PERMISSIONS: tuple[str, ...] = ("Channel.ReadBasic.All",)

# Window size and limit cap. Graph accepts no `$top` here; this bounds requests per call.
MAX_CHANNELS = 200

# Excludes `email` (expensive). Excludes `isArchived`: archived channels are a Teams preview
# feature. Excludes `layoutType`: Graph documents it as always null on this collection.
_CHANNEL_FIELDS = ("id", "displayName", "description", "createdDateTime", "membershipType")

# `membershipType` is an evolvable enum, and `shared` sits after the `unknownFutureValue` sentinel
# in it: Graph answers a shared channel with the sentinel unless the request asks for unknown
# members. The sentinel is worse here than a null — the SDK's enum names a member for that literal,
# so it reaches the answer as the word `unknownFutureValue`, which says nothing about the channel.
# Graph filters on the real value either way, so `$filter=membershipType eq 'shared'` needs no
# header; this listing reports the type rather than filtering on it, and so does need one.
_PREFER_UNKNOWN_ENUMS = ("Prefer", "include-unknown-enum-members")

type _ChannelsQuery = ChannelsRequestBuilder.ChannelsRequestBuilderGetQueryParameters

_DESCRIPTION = f"""\
List channels of a Microsoft Teams team. Pass the `team_id` from list_teams.

Call this to find the channel to browse, then pass `team_id` and `channel_id` together to \
browse_channel — a channel id alone addresses nothing. Channel names are unique only inside their \
own team (every team has a `General`), which is why the pair is always needed. No message content \
is returned here.

The list shows only channels the signed-in user can access. An absent channel means the user \
cannot access it, not that the team lacks it.

Microsoft Graph applies no page size to this collection. As many channels as `limit` means more \
may exist; fewer than `limit` is all of them the user can see. Raise `limit` (up to \
{MAX_CHANNELS}).\
"""


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
            "The channel name, e.g. `General`. Names are unique only inside their own team."
        )
    )
    description: str | None = Field(
        description="What the channel is for, as its owners wrote it. Often null."
    )
    membership_type: str | None = Field(
        description=(
            "`standard` for all team members, `private` for a member-list channel, or `shared` "
            + "for a channel shared with other teams. Null for a type Microsoft adds after this "
            + "code. Channels the user is not a member of do not appear."
        )
    )
    created_at: datetime | None = Field(
        description="When the channel was created — useful to tell apart similarly named channels."
    )


class ChannelList(BaseModel):
    channels: list[ChannelSummary] = Field(
        description=(
            "Channels the user can access. As many as `limit` means more may exist; fewer is all "
            + "of them. No cursor; raise `limit` (up to "
            + f"{MAX_CHANNELS}). Microsoft Graph does not order this collection."
        )
    )


async def list_channels(client: GraphServiceClient, *, team_id: str, limit: int) -> ChannelList:
    """The channels of `team_id` the signed-in user can see, up to `limit`."""
    assert 1 <= limit <= MAX_CHANNELS, f"limit must be within 1..{MAX_CHANNELS}, got {limit}"

    headers = _headers()
    configuration = RequestConfiguration[_ChannelsQuery](
        query_parameters=ChannelsRequestBuilder.ChannelsRequestBuilderGetQueryParameters(
            select=list(_CHANNEL_FIELDS)
        ),
        headers=headers,
    )
    with graph_errors(TOOL_NAME):
        first_page = await client.teams.by_team_id(team_id).channels.get(
            request_configuration=configuration
        )
        assert first_page is not None, "Graph answered a channel listing with no collection"
        collected = await collect_pages(first_page, client, limit=limit, headers=headers)

    return ChannelList(channels=[_channel(channel) for channel in collected.items])


def _headers() -> HeadersCollection:
    """A `HeadersCollection` with the `Prefer` header, for the first page and every page after it.

    Built per request: the default is shared by all configurations, so adding to it would affect
    every Graph request this connector makes.
    """
    headers = HeadersCollection()
    headers.add(*_PREFER_UNKNOWN_ENUMS)
    return headers


def _channel(channel: Channel) -> ChannelSummary:
    assert channel.id is not None, "Graph returned a channel with no id"
    # `ChannelMembershipType` subclasses `str`; each member equals its own wire value. A type the
    # SDK's enum names no member for deserializes to None rather than raising.
    return ChannelSummary(
        channel_id=channel.id,
        display_name=channel.display_name,
        description=channel.description,
        membership_type=channel.membership_type,
        created_at=channel.created_date_time,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Register this tool with the shared Graph transport.

    The tool borrows `transport` per call and does not own it. `create_app` closes it on
    shutdown.
    """
    # Built here because this is where `transport` is, and named rather than called in the default.
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List a Team's Channels",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def list_a_teams_channels(
        team_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The team whose channels to list, exactly as list_teams reported it. "
                    + "Opaque — copy it rather than constructing it. A team name is not one; "
                    + "names can repeat within a tenant, but team_ids do not."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_CHANNELS,
                description=(
                    "How many channels to return. Default 50, maximum "
                    + f"{MAX_CHANNELS}. Microsoft Graph applies no page size; this is the "
                    + "window applied while paging."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> ChannelList:
        return await list_channels(client, team_id=team_id, limit=limit)
