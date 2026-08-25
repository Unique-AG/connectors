"""`list_teams`: the query Graph accepts here, and what a full window promises."""

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.tools import list_teams as lister

from .conftest import GRAPH_V1


def _team_payload(
    team_id: str, *, display_name: str | None = "Engineering", is_archived: bool | None = False
) -> dict[str, object]:
    """Only these five are populated on `/me/joinedTeams`; the nulls are Graph's."""
    return {
        "id": team_id,
        "displayName": display_name,
        "description": "Synthetic team",
        "isArchived": is_archived,
        "tenantId": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
        "webUrl": None,
        "createdDateTime": None,
        "visibility": None,
    }


class TestTheQueryItSends:
    async def test_listing_teams_sends_no_odata_parameters_at_all(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """An unsupported OData parameter here is a 400, not a narrower answer.
        `services/teams-mcp` shipped the `$top` and had to take it back out."""
        route = graph.get("/me/joinedTeams").mock(
            return_value=httpx.Response(200, json={"value": [_team_payload("team-a")]})
        )

        _ = await lister.list_teams(client, limit=10)

        assert not route.calls.last.request.url.params, (
            "no OData parameter is supported on this collection"
        )

    @pytest.mark.parametrize("limit", [0, lister.MAX_TEAMS + 1])
    async def test_a_limit_outside_the_window_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await lister.list_teams(client, limit=limit)


class TestTheInventoryItReports:
    async def test_a_team_carries_what_graph_populates_and_nothing_it_does_not(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/joinedTeams").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _team_payload("team-live", display_name="Engineering"),
                        _team_payload("team-old", display_name="Engineering", is_archived=True),
                    ]
                },
            )
        )

        listed = await lister.list_teams(client, limit=25)

        assert [team.team_id for team in listed.teams] == ["team-live", "team-old"]
        assert [team.is_archived for team in listed.teams] == [False, True], (
            "the flag that tells two teams of the same name apart"
        )

    async def test_a_team_graph_gave_no_archive_flag_for_is_not_claimed_to_be_live(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/joinedTeams").mock(
            return_value=httpx.Response(
                200, json={"value": [_team_payload("team-a", is_archived=None)]}
            )
        )

        listed = await lister.list_teams(client, limit=25)

        assert listed.teams[0].is_archived is None

    async def test_an_empty_page_in_the_middle_does_not_end_the_collection(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph sends the occasional empty page with a cursor still set, and the SDK's own page
        walker reads one as the end of the collection."""
        graph.get("/me/joinedTeams", params={"$skiptoken": "third"}).mock(
            return_value=httpx.Response(200, json={"value": [_team_payload("team-c")]})
        )
        graph.get("/me/joinedTeams", params={"$skiptoken": "second"}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.nextLink": f"{GRAPH_V1}/me/joinedTeams?$skiptoken=third",
                },
            )
        )
        graph.get("/me/joinedTeams").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [_team_payload("team-a")],
                    "@odata.nextLink": f"{GRAPH_V1}/me/joinedTeams?$skiptoken=second",
                },
            )
        )

        listed = await lister.list_teams(client, limit=25)

        assert [team.team_id for team in listed.teams] == ["team-a", "team-c"]
        assert len(listed.teams) < 25, (
            "the walk reached the end of the collection, and a window short of `limit` is the "
            "whole of how that is reported"
        )

    async def test_a_full_window_of_teams_is_all_a_full_window_promises(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/joinedTeams").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [_team_payload(f"team-{index}") for index in range(2)],
                    "@odata.nextLink": f"{GRAPH_V1}/me/joinedTeams?$skiptoken=synthetic",
                },
            )
        )

        listed = await lister.list_teams(client, limit=2)

        assert len(listed.teams) == 2, (
            "a window filled to `limit` is the whole of what a caller is told; Graph had a next "
            "link here and the page behind it is not fetched to be discarded"
        )
        assert len(graph.calls) == 1


class TestGraphFailures:
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        denied = httpx.Response(
            403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
        )
        graph.get("/me/joinedTeams").mock(return_value=denied)

        with pytest.raises(GraphForbidden):
            _ = await lister.list_teams(client, limit=25)

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Team.ReadBasic.All",)
