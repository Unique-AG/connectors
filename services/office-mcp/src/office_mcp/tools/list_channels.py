"""`list_channels` — the channels of one team the signed-in user can see.

The middle step of the channel path: `list_teams` names a team and this names a channel inside it.
The pair is always needed, because a channel name is unique only inside its own team — every team
has a `General` — and a channel id alone addresses nothing in Graph, which is why the handle
`read_message` takes for a channel message carries both.

**`$select` here is a requirement rather than an optimisation.** Graph documents populating a
channel's `email` as "an expensive operation that results in slow performance"
(https://learn.microsoft.com/en-us/graph/api/channel-list), and selecting around it is the only way
not to pay for it. The same reference gives this collection `$select` and `$filter` and nothing
else — no `$top`, which `services/teams-mcp` shipped and had to take back out — so the window is
applied while walking the pages Graph chose, exactly as `list_teams` does.

The collection is already access-trimmed: "Teams members can't see private or shared channels that
they aren't members of in the response for this API". That is why an absent channel is not evidence
that the team has no such channel, and why the description says so rather than leaving a model to
conclude it.

What this file does not own is the token and the refusal wording (`shared/seam.py`, so this tool's
403 sounds like every other tool's). Everything else — the name, the description, the permission,
the fields asked for, the window, the answer shape and the request — is here.
"""

from datetime import datetime
from typing import Annotated

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.channel import Channel
from msgraph.generated.teams.item.channels.channels_request_builder import ChannelsRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import collect_pages, graph_client_for, graph_errors
from office_mcp.shared.seam import READ_ONLY, graph_token, graph_tool_errors

TOOL_NAME = "list_channels"

# The delegated Graph permission this tool's one request needs — the cheap "basic" scope over a
# channel's identity, which is all this collection returns. Reading what was *posted* in a channel
# is the broad `ChannelMessage.Read.All`, which the tools that read messages declare; a tenant
# commonly grants this one and withholds that one, which is why the two are named separately.
GRAPH_PERMISSIONS: tuple[str, ...] = ("Channel.ReadBasic.All",)

# Built once at import: a call inside a parameter default rebuilds the descriptor on every
# registration and is a lint error in both of this repo's checkers.
_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

# How many channels one call returns, and the ceiling on `limit`. Graph takes no `$top` on this
# collection either, so this window is this connector's own and so is its bound: it caps the number
# of Graph requests one call can make while walking the pages.
MAX_CHANNELS = 200

# What a channel listing asks for, which is everything Graph populates that identifies a channel.
# `email` is excluded deliberately (see the module docstring), and so is `isArchived`: Graph
# documents `layoutType` as coming back null on this collection and archived channels are a Teams
# preview concept, so neither is claimed here.
_CHANNEL_FIELDS = ("id", "displayName", "description", "createdDateTime", "membershipType")

type _ChannelsQuery = ChannelsRequestBuilder.ChannelsRequestBuilderGetQueryParameters

_DESCRIPTION = f"""\
List the channels of one Microsoft Teams team, identified by the `team_id` list_teams returned: \
each channel's id, name, description, membership type and creation date.

Call this to see what channels a team has, and to put a name to the `channel_id` search_messages \
reports on a channel message — a channel id alone addresses nothing. Channel names are unique only \
inside their own team (every team has a `General`), which is why the pair is always needed. No \
message content is returned here.

The list is already trimmed to what the signed-in user may see: Microsoft omits private and shared \
channels they are not a member of, so an absent channel is not evidence that the team has no such \
channel. `membership_type` says which kind each one is — `standard`, `private` or `shared`.

There is no pagination and no ordering, for the same reason as list_teams: Microsoft accepts no \
page size on this collection either. As many channels as `limit` means the team may have more; \
fewer than `limit` is all of them this user can see. Widen `limit` (up to {MAX_CHANNELS}).\
"""


class ChannelSummary(BaseModel):
    channel_id: str = Field(
        description=(
            "The channel's Graph id, e.g. `19:...@thread.tacv2`. It is the id search_messages "
            + "reports as `channel_id` on a channel message, and it addresses a channel only "
            + "together with its `team_id`. Opaque — copy it rather than constructing one from a "
            + "name."
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
            + f"cursor: raise `limit` (up to {MAX_CHANNELS}). Microsoft Graph applies no order to "
            + "this collection either."
        )
    )


async def list_channels(client: GraphServiceClient, *, team_id: str, limit: int) -> ChannelList:
    """The channels of `team_id` the signed-in user can see, up to `limit`."""
    assert 1 <= limit <= MAX_CHANNELS, f"limit must be within 1..{MAX_CHANNELS}, got {limit}"

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


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this tool against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tool
    borrows it per call and never owns it. `create_app` closes it on shutdown.
    """

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
                    "The team whose channels to list, exactly as list_teams reported its "
                    + "`team_id`. Opaque — a team's name is not one, and one cannot be "
                    + "constructed."
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
                    + f"{MAX_CHANNELS} — as with list_teams, Microsoft Graph applies no "
                    + "page size here and this is the window applied while paging."
                ),
            ),
        ] = 50,
        graph_token: str = _TOKEN,
    ) -> ChannelList:
        with graph_tool_errors(*GRAPH_PERMISSIONS):
            return await list_channels(
                graph_client_for(transport, graph_token), team_id=team_id, limit=limit
            )
