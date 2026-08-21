"""`list_teams`: the query Graph accepts here, and what a full window promises.

The load-bearing assertion is about a parameter that is *not* sent. Graph answers an unsupported
OData parameter on `/me/joinedTeams` with a 400, and `services/teams-mcp` shipped a `$top` on it and
had to take it back out, so no `$top` is a contract rather than an omission.

Every payload is synthesised from Microsoft's documented shapes.
"""

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphForbidden
from office_mcp.tools import list_teams as lister

from .conftest import GRAPH_V1


def _team_payload(
    team_id: str, *, display_name: str | None = "Engineering", is_archived: bool | None = False
) -> dict[str, object]:
    """One `team` as `GET /me/joinedTeams` returns it.

    Only these five properties are populated on that endpoint. The nulls are Graph's, not this
    fixture's shorthand.
    """
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
        """`/me/joinedTeams` supports none of them, so a `$top` or a `$select` here is a 400 and
        not a narrower answer. teams-mcp shipped the `$top` and had to remove it."""
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
        """The tool's schema bounds `limit`, so a value outside it can only arrive from code that
        bypassed it."""
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
        """The load-bearing case for the other half of what this answer promises: fewer teams than
        `limit` is every team the user is in.

        Graph answers the occasional page with nothing in it and a cursor still set, and the SDK's
        own page walker reads an empty page as the end of a collection. Believing it here would not
        merely drop a team. It would turn a window with more behind it into "you are in one team",
        which is a claim about the user's own tenant that nothing checked. This tool cannot even
        ask for a smaller collection to make the walk shorter, since `/me/joinedTeams` takes no
        `$top`, so the sentence is only true while every page is followed.
        """
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
        """This request is made under its own delegated permission, and a tenant commonly grants
        the two basic ones while withholding the broad message permission, so the failure has to
        reach the tool layer, which is what names the permission."""
        denied = httpx.Response(
            403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
        )
        graph.get("/me/joinedTeams").mock(return_value=denied)

        with pytest.raises(GraphForbidden):
            _ = await lister.list_teams(client, limit=25)

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        """A tool owns the permission its own request needs, and this collection is behind the
        cheap "basic" scope over a team's identity."""
        assert lister.GRAPH_PERMISSIONS == ("Team.ReadBasic.All",)
