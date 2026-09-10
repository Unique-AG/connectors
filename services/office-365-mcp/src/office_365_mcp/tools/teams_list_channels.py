"""`teams_list_channels` — channels of one team the signed-in user can access.

TRAP: `$select` is a requirement, not an optimization — it excludes `email`, which Graph documents
as "an expensive operation that results in slow performance". The collection accepts no `$top`
(Graph returns 400), so the window is this connector's own, applied while walking pages.

**`membership_type` is a real `$filter`, and one of few on any Teams collection.** Microsoft
publishes "This method supports the $filter and $select OData query parameters" for this
collection, and backs it with worked examples naming the property — `channels?$filter=
membershipType eq 'private'` among them (https://learn.microsoft.com/en-us/graph/api/channel-list).
So this bound goes to the server rather than filtering rows here.

**And it is checked on the way back, because a `$filter` Graph does not honour is documented to
fail in silence** rather than with an error
(https://learn.microsoft.com/en-us/graph/query-parameters). Dropped, the filter would answer with
every channel of the team under an argument that named one kind — and `ChannelList.channels`
promises that fewer rows than `limit` means those are all of them, so a caller reading a full
inventory as "all the private channels" has no way to tell. The check raises rather than
discarding the wrong rows: discarding would keep that promise intact while quietly turning a
dropped filter into a false "none found". `membershipType` is already in `$select`, so it costs
nothing.
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

# This permission is not `ChannelMessage.Read.All`, which teams_browse_channel declares to read
# posted messages. A tenant commonly grants one and withholds the other.
GRAPH_PERMISSIONS: tuple[str, ...] = ("Channel.ReadBasic.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d"}

MAX_CHANNELS = 200

# Excludes `isArchived` (a Teams preview) and `layoutType` (Graph documents it as always null).
_CHANNEL_FIELDS = ("id", "displayName", "description", "createdDateTime", "membershipType")

# TRAP: without this header Graph answers a shared channel's `membershipType` with the literal
# `unknownFutureValue` — `shared` sits after that sentinel in the evolvable enum. A `$filter` on
# the real value needs no header. This listing reports the type instead, so it needs the header.
_PREFER_UNKNOWN_ENUMS = ("Prefer", "include-unknown-enum-members")

# The three kinds Microsoft names. `unknownFutureValue` is the evolvable-enum sentinel rather than
# a kind of channel, so it is not offered: filtering on it asks for the marker, not for whatever
# Microsoft adds next. A closed set is also what keeps this value out of reach of an OData literal
# escape — nothing a caller writes reaches the query string.
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
List one team's channels. Pass the `team_id` from teams_list_my_teams. Then hand `team_id` and \
`channel_id` together to teams_browse_channel. A channel id alone addresses nothing, and every \
team has a `General`. Pass `membership_type` for "the private channels" or "the shared ones"; \
omit it for all of them. No message text comes back here: teams_browse_channel reads the posts. A \
channel missing from the list is one the signed-in user cannot access, not one the team lacks. \
Returns each channel's id, name, description, membership type, and creation date.\
"""


class ChannelSummary(BaseModel):
    channel_id: str = Field(
        description=(
            "The channel's Graph id, for example `19:...@thread.tacv2`. Pass it with its "
            + "`team_id` to "
            + "teams_browse_channel. It is also the id teams_search_messages reports as "
            + "`channel_id` on "
            + "a "
            + "channel message. This id is opaque — copy it rather than constructing one from "
            + "a name."
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
            "`standard` for all team members, `private` for a member-list channel, or `shared` "
            + "for a channel shared with other teams. Null for a type that Microsoft adds after "
            + "this code. Channels the user is not a member of do not appear."
        )
    )
    created_at: datetime | None = Field(
        description="When the channel was created — useful to tell apart similarly named channels."
    )

    @classmethod
    def from_channel(cls, channel: Channel) -> Self:
        assert channel.id is not None, "Graph returned a channel with no id"
        # `ChannelMembershipType` subclasses `str`. An unnamed type becomes None. It never raises.
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
            "Channels the user can access. As many as `limit` can mean more exist. Fewer is all "
            + "of them. No cursor. Raise `limit` (up to "
            + f"{MAX_CHANNELS}). Microsoft Graph does not order this collection."
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
    """Refuse an answer holding a channel of a kind nobody asked for. See the module docstring.

    A row whose `membership_type` is null passes: Microsoft can add a kind after this code, and the
    `Prefer` header asks for the real name of one, so a null here is a kind this tool cannot name
    rather than evidence about the filter. A row naming a DIFFERENT one of the three is the
    evidence, and it is what a dropped filter produces.
    """
    if membership_type is None:
        return
    # Case-folded, for the same reason `outlook_list_mail` folds a sender address: the answer
    # echoes whatever spelling Microsoft 365 holds, not the spelling that was filtered with. A
    # bare `!=` turns a `Private` where `private` was asked into a refused answer that was right.
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
                    "Only channels of this kind: `standard` for the ones every team member is in, "
                    + "`private` for a member-list channel, or `shared` for one shared with other "
                    + "teams. The same three words each row reports in `membership_type`, so an "
                    + "answer can be narrowed with a value read straight out of an earlier one. "
                    + "Microsoft 365 applies this, so it does not spend the window on channels "
                    + "that were then discarded. Omit it for every kind, which is the usual call."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_CHANNELS,
                description=(
                    "How many channels to return. Default 50, maximum "
                    + f"{MAX_CHANNELS}. Microsoft Graph applies no page size. This is the "
                    + "window applied while paging."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> ChannelList:
        return await teams_list_channels(
            client, team_id=team_id, membership_type=membership_type, limit=limit
        )
