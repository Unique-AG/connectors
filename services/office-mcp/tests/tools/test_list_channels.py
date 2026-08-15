"""`list_channels`: what the query asks for, what it declines, and the pages it follows.

Two of the assertions here are about parameters. `$select` is a requirement rather than an
optimisation — Graph documents populating a channel's `email` as an expensive operation — and `$top`
is one Graph answers with a 400, which `services/teams-mcp` shipped and had to take back out.

Every payload is synthesised from Microsoft's documented shapes.
"""

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphForbidden
from office_mcp.tools import list_channels as lister

from .conftest import GRAPH_V1

_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"
_CHANNELS_PATH = f"/teams/{_TEAM_ID}/channels"


def _channel_payload(
    channel_id: str,
    *,
    display_name: str = "General",
    membership_type: str = "standard",
) -> dict[str, object]:
    return {
        "id": channel_id,
        "displayName": display_name,
        "description": "Synthetic channel",
        "createdDateTime": "2026-01-04T12:00:00Z",
        "membershipType": membership_type,
    }


class TestTheQueryItSends:
    async def test_listing_channels_selects_around_the_expensive_property(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph documents populating a channel's `email` as an expensive operation, and `$select`
        is the only way to decline it. `$top` is unsupported here too."""
        route = graph.get(_CHANNELS_PATH).mock(
            return_value=httpx.Response(200, json={"value": [_channel_payload(_CHANNEL_ID)]})
        )

        _ = await lister.list_channels(client, team_id=_TEAM_ID, limit=10)

        params = route.calls.last.request.url.params
        assert params["$select"] == "id,displayName,description,createdDateTime,membershipType"
        assert "email" not in params["$select"]
        assert "$top" not in params, "$top is rejected on this collection"

    @pytest.mark.parametrize("limit", [0, lister.MAX_CHANNELS + 1])
    async def test_a_limit_outside_the_window_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        """The tool's schema bounds `limit`, so a value outside it can only arrive from code that
        bypassed it."""
        with pytest.raises(AssertionError):
            _ = await lister.list_channels(client, team_id=_TEAM_ID, limit=limit)


class TestTheInventoryItReports:
    async def test_the_channel_pages_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """This collection takes no `$top`, so Graph chooses the page size and a second page is
        normal. teams-mcp read only the first one until it was fixed ("page teams/channels
        lists"), which silently hid channels from the listing.
        """
        graph.get(_CHANNELS_PATH, params={"$skiptoken": "synthetic"}).mock(
            return_value=httpx.Response(
                200, json={"value": [_channel_payload("19:second@thread.tacv2")]}
            )
        )
        graph.get(_CHANNELS_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [_channel_payload(_CHANNEL_ID)],
                    "@odata.nextLink": f"{GRAPH_V1}{_CHANNELS_PATH}?$skiptoken=synthetic",
                },
            )
        )

        listed = await lister.list_channels(client, team_id=_TEAM_ID, limit=25)

        assert [channel.channel_id for channel in listed.channels] == [
            _CHANNEL_ID,
            "19:second@thread.tacv2",
        ]
        assert len(listed.channels) < 25, "the walk reached the end of the collection"

    async def test_an_empty_page_in_the_middle_does_not_end_the_collection(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The load-bearing case for the other half of what this answer promises: fewer channels
        than `limit` is every channel of this team the user can see.

        Graph answers the odd page with nothing in it and an `@odata.nextLink` still set, and the
        SDK's own page walker reads an empty page as the end of a collection. Believing it here
        would not merely drop a channel — it would turn a window with more behind it into "this
        team has one channel", a claim about the user's own team that nothing checked. The
        sentence in the description is therefore only true while every page is followed, and this
        is the test that says so for this collection rather than for paging in general.
        """
        graph.get(_CHANNELS_PATH, params={"$skiptoken": "third"}).mock(
            return_value=httpx.Response(
                200, json={"value": [_channel_payload("19:third@thread.tacv2")]}
            )
        )
        graph.get(_CHANNELS_PATH, params={"$skiptoken": "second"}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.nextLink": f"{GRAPH_V1}{_CHANNELS_PATH}?$skiptoken=third",
                },
            )
        )
        graph.get(_CHANNELS_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [_channel_payload(_CHANNEL_ID)],
                    "@odata.nextLink": f"{GRAPH_V1}{_CHANNELS_PATH}?$skiptoken=second",
                },
            )
        )

        listed = await lister.list_channels(client, team_id=_TEAM_ID, limit=25)

        assert [channel.channel_id for channel in listed.channels] == [
            _CHANNEL_ID,
            "19:third@thread.tacv2",
        ]

    async def test_a_channels_membership_type_comes_through_and_an_unknown_one_does_not_fail(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A `membershipType` the SDK's generated enum has no member for deserializes to None
        rather than raising, so the channel must still be listed."""
        graph.get(_CHANNELS_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _channel_payload(_CHANNEL_ID, membership_type="private"),
                        _channel_payload("19:future@thread.tacv2", membership_type="hypothetical"),
                    ]
                },
            )
        )

        listed = await lister.list_channels(client, team_id=_TEAM_ID, limit=25)

        assert [channel.membership_type for channel in listed.channels] == ["private", None]
        created = listed.channels[0].created_at
        assert created is not None and created.year == 2026


class TestGraphFailures:
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """This request is made under its own delegated permission — a tenant commonly grants the
        two basic ones and withholds the broad message permission — so the failure has to reach the
        tool layer, which is what names the permission."""
        denied = httpx.Response(
            403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
        )
        graph.get(_CHANNELS_PATH).mock(return_value=denied)

        with pytest.raises(GraphForbidden):
            _ = await lister.list_channels(client, team_id=_TEAM_ID, limit=25)

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        """A tool owns the permission its own request needs, and listing channels is the cheap
        "basic" scope — reading what was posted in one is the broader `ChannelMessage.Read.All`."""
        assert lister.GRAPH_PERMISSIONS == ("Channel.ReadBasic.All",)
