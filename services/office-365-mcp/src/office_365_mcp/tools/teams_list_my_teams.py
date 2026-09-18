"""`teams_list_my_teams` — the teams the signed-in user is a member of.

TRAP: Graph accepts no OData query on this collection. `$top`, `$select` and `$filter` all return
400, so this tool sends no request configuration. services/teams-mcp shipped `$top` and removed it.

Only five properties populate: `id`, `displayName`, `description`, `isArchived`, `tenantId`.
"""

from collections.abc import Mapping
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.team import Team
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_list_my_teams"

STEP = "joined_teams"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Team.ReadBasic.All",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

MAX_TEAMS = 200

_DESCRIPTION = """\
Lists the teams the signed-in user belongs to, in no particular order, as the starting point for \
any question about a team or a channel. It does not cover chats, group chats, or meeting chats — \
the other surface entirely — use teams_list_chats for those.\
"""


class TeamSummary(BaseModel):
    team_id: str = Field(
        description=(
            "The team's Graph id. Pass it to teams_list_channels, and match it against the "
            + "`team_id` teams_search_messages reports on channel messages. Opaque — copy it "
            + "verbatim, never build one from a name."
        )
    )
    display_name: str | None = Field(
        description="The team name. Multiple teams can share the same name."
    )
    description: str | None = Field(
        description="The team purpose, written by owners. Null if not set."
    )
    is_archived: bool | None = Field(
        description=(
            "True if archived (read-only in Teams). Use with `description` to tell apart "
            + "teams with the same name. Null if not stated."
        )
    )

    @classmethod
    def from_team(cls, team: Team) -> Self:
        assert team.id is not None
        return cls(
            team_id=team.id,
            display_name=team.display_name,
            description=team.description,
            is_archived=team.is_archived,
        )


class TeamList(BaseModel):
    teams: list[TeamSummary] = Field(
        description=(
            "The user's teams, in no particular order — Microsoft Graph applies none to this "
            + "collection. A full window can mean more teams exist; a shorter one is the "
            + "complete list."
        )
    )


async def teams_list_my_teams(client: GraphServiceClient, *, limit: int) -> TeamList:
    assert 1 <= limit <= MAX_TEAMS, f"limit must be within 1..{MAX_TEAMS}, got {limit}"

    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.me.joined_teams.get()
        assert first_page is not None, "Graph answered GET /me/joinedTeams with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return TeamList(teams=[TeamSummary.from_team(team) for team in collected.items])


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List My Teams",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def list_my_teams(
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_TEAMS,
                description=(
                    f"Teams to return, 1–{MAX_TEAMS}. The result is already the whole answer for "
                    + "this call: repeating it with the same `limit` returns the same teams, not "
                    + "the next page — raise `limit` to see more."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> TeamList:
        return await teams_list_my_teams(client, limit=limit)
