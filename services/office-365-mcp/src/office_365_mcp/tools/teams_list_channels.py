"""`teams_list_channels` — channels of one team the signed-in user can access.

TRAP: `$select` excludes `email`, which Graph documents as an expensive property, and the
collection rejects `$top` with a 400 — so the window is applied while walking pages.
`membership_type` is a real `$filter` (https://learn.microsoft.com/en-us/graph/api/channel-list),
and it is checked on the way back because a `$filter` Graph does not honour fails in silence
rather than with an error (https://learn.microsoft.com/en-us/graph/query-parameters).
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
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

# Not `ChannelMessage.Read.All`, which teams_browse_channel declares: a tenant commonly grants one
# and withholds the other.
GRAPH_PERMISSIONS: tuple[str, ...] = ("Channel.ReadBasic.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d"}

MAX_CHANNELS = 200

# Excludes `isArchived` (a Teams preview) and `layoutType` (Graph documents it as always null).
_CHANNEL_FIELDS = ("id", "displayName", "description", "createdDateTime", "membershipType")

# TRAP: without this header Graph reports a shared channel's `membershipType` as the literal
# `unknownFutureValue` — `shared` sits after that sentinel in the evolvable enum.
_PREFER_UNKNOWN_ENUMS = ("Prefer", "include-unknown-enum-members")

# Closed set: this value is interpolated into `$filter`, so nothing a caller writes can reach the
# query string.
type ChannelMembership = Literal["standard", "private", "shared"]

type _ChannelsQuery = ChannelsRequestBuilder.ChannelsRequestBuilderGetQueryParameters

_FILTER_IGNORED = (
    "Microsoft 365 answered this channel listing with channels of a kind other than the "
    + "`membership_type` that was asked for, which means it did not apply the filter this tool "
    + "sent. Microsoft documents that Graph can ignore a query parameter silently rather than "
    + "refuse it, so this tool checks the answer instead of trusting it. It reports no channels, "
    + "because the alternative is the team's whole channel inventory presented as the channels of "
    + "one kind. Call teams_list_channels again without `membership_type` and read each row's "
    + "`membership_type` instead."
)

_DESCRIPTION = """\
Lists the channels of one team the signed-in user can access, in no particular order, for finding \
a channel's `channel_id` before browsing or searching it. It carries no message text — \
teams_browse_channel reads the posts, and teams_search_messages finds one by content.

Notes:
- A channel absent from the list is one the signed-in user cannot access, not one the team \
lacks.
- A channel id alone addresses nothing. Pass it together with `team_id` to teams_browse_channel.\
"""


class ChannelSummary(BaseModel):
    channel_id: str = Field(
        description=(
            "The channel's Graph id, for example `19:...@thread.tacv2`. Pass it with its "
            + "`team_id` to teams_browse_channel. Match it against the `channel_id` that "
            + "teams_search_messages reports on a channel message. This id is opaque — copy it "
            + "rather than building one from a name."
        )
    )
    display_name: str | None = Field(
        description=(
            "The channel name, for example `General`. Names are unique only inside their own "
            + "team."
        )
    )
    description: str | None = Field(
        description="What the channel is for, as its owners wrote it. Often null."
    )
    membership_type: str | None = Field(
        description=(
            "One of `standard`, `private`, or `shared`, or null for a type Microsoft adds after "
            + "this connector. Channels the user is not a member of do not appear."
        )
    )
    created_at: datetime | None = Field(
        description="When the channel was created — useful to tell apart similarly named channels."
    )

    @classmethod
    def from_channel(cls, channel: Channel) -> Self:
        assert channel.id is not None, "Graph returned a channel with no id"
        # `ChannelMembershipType` subclasses `str`; a kind this SDK cannot name becomes None.
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
            "Channels the user can access, in no particular order — Microsoft Graph applies none "
            + "to this collection. A full window can mean more channels exist. A shorter one is "
            + "the complete list."
        )
    )


async def teams_list_channels(
    client: GraphServiceClient,
    *,
    team_id: str,
    membership_type: ChannelMembership | None = None,
    limit: int,
) -> ChannelList:
    assert 1 <= limit <= MAX_CHANNELS, f"limit must be within 1..{MAX_CHANNELS}, got {limit}"

    headers = _headers()
    configuration = RequestConfiguration[_ChannelsQuery](
        query_parameters=ChannelsRequestBuilder.ChannelsRequestBuilderGetQueryParameters(
            select=list(_CHANNEL_FIELDS),
            filter=None if membership_type is None else f"membershipType eq '{membership_type}'",
        ),
        headers=headers,
    )
    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.teams.by_team_id(team_id).channels.get(
            request_configuration=configuration
        )
        assert first_page is not None, "Graph answered a channel listing with no collection"
        collected = await collect_pages(first_page, client, limit=limit, headers=headers)

    channels = [ChannelSummary.from_channel(channel) for channel in collected.items]
    _make_sure_the_filter_was_applied(channels, membership_type)
    return ChannelList(channels=channels)


def _make_sure_the_filter_was_applied(
    channels: list[ChannelSummary], membership_type: ChannelMembership | None
) -> None:
    """Refuse an answer holding a channel of a kind nobody asked for.

    A null `membership_type` passes: it is a kind this tool cannot name, not evidence about the
    filter. Only a row naming a DIFFERENT one of the three is.
    """
    if membership_type is None:
        return
    # Case-folded: the answer echoes whatever spelling Microsoft 365 holds, not the one filtered on.
    wanted = membership_type.casefold()
    for channel in channels:
        recorded = channel.membership_type
        if recorded is not None and recorded.casefold() != wanted:
            raise ToolError(_FILTER_IGNORED)


def _headers() -> HeadersCollection:
    """Built per request. Adding to the shared default collection affects every Graph call."""
    headers = HeadersCollection()
    headers.add(*_PREFER_UNKNOWN_ENUMS)
    return headers


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
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
                    + "This id is opaque — copy it rather than constructing it. A team name is "
                    + "not one. Names can repeat within a tenant, but team_ids do not."
                ),
            ),
        ],
        membership_type: Annotated[
            ChannelMembership | None,
            Field(
                description=(
                    "Only channels of this kind: `standard`, `private`, or `shared`. `standard` "
                    + "is a channel every team member is in. `private` is a member-list channel. "
                    + "`shared` is a channel shared with other teams. Each row reports this same "
                    + "value in `membership_type`. Omit it for every kind."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_CHANNELS,
                description=(
                    f"How many channels to return, at most {MAX_CHANNELS}. The result is "
                    + "already the whole answer for this call. Repeating it with the same "
                    + "`limit` returns the same channels, not the next page. Raise `limit` to "
                    + "see more."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> ChannelList:
        return await teams_list_channels(
            client, team_id=team_id, membership_type=membership_type, limit=limit
        )
