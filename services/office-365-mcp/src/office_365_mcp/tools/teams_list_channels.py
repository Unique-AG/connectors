"""`teams_list_channels` — channels of one team the signed-in user can access.

TRAP: `$select` is a requirement, not an optimisation — it excludes `email`, which Graph documents
as "an expensive operation that results in slow performance". The collection accepts no `$top`
(Graph returns 400), so the window is this connector's own, applied while walking pages.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.channel import Channel
from msgraph.generated.teams.item.channels.channels_request_builder import ChannelsRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_list_channels"

STEP = "channels"

# Not `ChannelMessage.Read.All`, which teams_browse_channel declares to read what was posted: a
# tenant
# commonly grants one and withholds the other.
GRAPH_PERMISSIONS: tuple[str, ...] = ("Channel.ReadBasic.All",)

# Invented ids, but a shape this tool accepts: an argument it rejects never reaches Graph.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d"}

MAX_CHANNELS = 200

# Excludes `isArchived` (a Teams preview) and `layoutType` (Graph documents it as always null).
_CHANNEL_FIELDS = ("id", "displayName", "description", "createdDateTime", "membershipType")

# TRAP: without this header Graph answers a shared channel's `membershipType` with the literal
# `unknownFutureValue` — `shared` sits after that sentinel in the evolvable enum. A `$filter` on the
# real value needs no header; this listing reports the type instead, so it does.
_PREFER_UNKNOWN_ENUMS = ("Prefer", "include-unknown-enum-members")

type _ChannelsQuery = ChannelsRequestBuilder.ChannelsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
List one team's channels. Pass the `team_id` from teams_list_my_teams, then hand `team_id` and \
`channel_id` \
together to teams_browse_channel — a channel id alone addresses nothing, and every team has a \
`General`. \
No message text comes back here: teams_browse_channel reads the posts. A channel missing from the \
list \
is one the signed-in user cannot access, not one the team lacks. Returns each channel's id, name, \
description, membership type and creation date.\
"""


class ChannelSummary(BaseModel):
    channel_id: str = Field(
        description=(
            "The channel's Graph id, e.g. `19:...@thread.tacv2`. Pass it with its `team_id` to "
            + "teams_browse_channel; it is also the id teams_search_messages reports as "
            + "`channel_id` on "
            + "a "
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

    @classmethod
    def from_channel(cls, channel: Channel) -> Self:
        assert channel.id is not None, "Graph returned a channel with no id"
        # `ChannelMembershipType` subclasses `str`. An unnamed type becomes None, never raises.
        return cls(
            channel_id=channel.id,
            display_name=channel.display_name,
            description=channel.description,
            membership_type=channel.membership_type,
            created_at=channel.created_date_time,
        )


class ChannelList(BaseModel):
    channels: list[ChannelSummary] = Field(
        description=(
            "Channels the user can access. As many as `limit` means more may exist; fewer is all "
            + "of them. No cursor; raise `limit` (up to "
            + f"{MAX_CHANNELS}). Microsoft Graph does not order this collection."
        )
    )


async def teams_list_channels(
    client: GraphServiceClient, *, team_id: str, limit: int
) -> ChannelList:
    assert 1 <= limit <= MAX_CHANNELS, f"limit must be within 1..{MAX_CHANNELS}, got {limit}"

    headers = _headers()
    configuration = RequestConfiguration[_ChannelsQuery](
        query_parameters=ChannelsRequestBuilder.ChannelsRequestBuilderGetQueryParameters(
            select=list(_CHANNEL_FIELDS)
        ),
        headers=headers,
    )
    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.teams.by_team_id(team_id).channels.get(
            request_configuration=configuration
        )
        assert first_page is not None, "Graph answered a channel listing with no collection"
        collected = await collect_pages(first_page, client, limit=limit, headers=headers)

    return ChannelList(
        channels=[ChannelSummary.from_channel(channel) for channel in collected.items]
    )


def _headers() -> HeadersCollection:
    """Built per request: adding to the shared default collection would affect every Graph call."""
    headers = HeadersCollection()
    headers.add(*_PREFER_UNKNOWN_ENUMS)
    return headers


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    # Closes over `transport` here; the default below holds this name, not a call (ruff's B008).
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
                    "The team whose channels to list, exactly as teams_list_my_teams reported it. "
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
        return await teams_list_channels(client, team_id=team_id, limit=limit)
