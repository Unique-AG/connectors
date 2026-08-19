"""`list_teams` — the teams the signed-in user is a member of.

This tool complements `list_chats`. A chat is joined. A channel is browsed inside a team. No
tool reaches a channel without a team id first.

TRAP: Graph accepts no OData query on this collection. `$top`, `$select`, and `$filter` all
return 400. services/teams-mcp shipped `$top` and had to remove it. This tool sends no request
configuration.

Only five properties populate: `id`, `displayName`, `description`, `isArchived`, `tenantId`.
"""

from typing import Annotated

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.team import Team
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import collect_pages, graph_errors
from office_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "list_teams"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Team.ReadBasic.All",)

# A safety valve on Graph request count, not a Graph-imposed page size. Graph accepts no page
# size on this collection.
MAX_TEAMS = 200

_DESCRIPTION = """\
List the Microsoft Teams teams you are a member of, with each team's id, name, description, \
and archived flag.

This is the channel side of Teams. To read a channel message, first use this tool to find the \
team. The `team_id` is the same id search_messages reports on channel messages. The `limit` is \
a window over Microsoft's order; shorter than `limit` means end of list.\
"""


class TeamSummary(BaseModel):
    team_id: str = Field(
        description=(
            "The team's Graph id. This is the same id search_messages reports on channel "
            + "messages. Opaque—copy it verbatim, never build one from a name."
        )
    )
    display_name: str | None = Field(
        description="The team name. Multiple teams may share the same name."
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


class TeamList(BaseModel):
    teams: list[TeamSummary] = Field(
        description=(
            "Your teams. Full window (`limit` teams) means more may exist; teams beyond a "
            + "full window are arbitrary, not ranked by importance. Short window means end of "
            + f"list. Raise `limit` (up to {MAX_TEAMS}) to see more."
        )
    )


async def list_teams(client: GraphServiceClient, *, limit: int) -> TeamList:
    """Return up to `limit` teams."""
    assert 1 <= limit <= MAX_TEAMS, f"limit must be within 1..{MAX_TEAMS}, got {limit}"

    with graph_errors(TOOL_NAME):
        first_page = await client.me.joined_teams.get()
        assert first_page is not None, "Graph answered GET /me/joinedTeams with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return TeamList(teams=[_team(team) for team in collected.items])


def _team(team: Team) -> TeamSummary:
    assert team.id is not None
    return TeamSummary(
        team_id=team.id,
        display_name=team.display_name,
        description=team.description,
        is_archived=team.is_archived,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Register this tool."""
    # Built here because this is where `transport` is, and named rather than called in the default.
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
                    f"Teams to return, 1–{MAX_TEAMS}. Default 50. Microsoft Graph applies no page "
                    + "size to this collection; this is a window this connector applies while "
                    + "paging. Shorter than `limit` means end of list."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> TeamList:
        return await list_teams(client, limit=limit)
