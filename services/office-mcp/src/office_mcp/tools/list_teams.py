"""`list_teams` — the teams the signed-in user is a member of.

This tool complements `list_chats`: a user joins a chat and browses a channel inside a team. No
tool reaches a channel without a team id first.

TRAP: Graph accepts no OData query on this collection. `$top`, `$select`, and `$filter` all return
400, so this tool sends no request configuration. services/teams-mcp shipped `$top` and had to
remove it.

Only five properties populate: `id`, `displayName`, `description`, `isArchived`, `tenantId`.
"""

from collections.abc import Mapping
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.team import Team
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import collect_pages, graph_errors
from office_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "list_teams"

# The one Graph call this tool makes, as the step instruments count it.
STEP = "joined_teams"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Team.ReadBasic.All",)

# One call that reaches Graph, read by `tools/__init__.py` into the coverage table
# `tests/test_error_mapping.py` refuses every registered tool from. This tool takes no arguments, so
# the one call needs none.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

# Caps `limit` and bounds Graph requests per call. Graph accepts no page size here.
MAX_TEAMS = 200

_DESCRIPTION = """\
List the Microsoft Teams teams you are a member of, with each team's id, name, description, \
and archived flag.

This is the channel side of Teams. To read a channel message, first use this tool to find the \
team, then list_channels to find the channel. The `team_id` is what list_channels takes, and the \
same id search_messages reports on channel messages. The `limit` is a window over Microsoft's \
order; shorter than `limit` means end of list.\
"""


class TeamSummary(BaseModel):
    team_id: str = Field(
        description=(
            "The team's Graph id. This is what list_channels takes, and the same id "
            + "search_messages reports on channel messages. Opaque—copy it verbatim, never "
            + "build one from a name."
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
            "Your teams. Full window (`limit` teams) means more may exist; teams beyond a "
            + "full window are arbitrary, not ranked by importance. Short window means end of "
            + f"list. Raise `limit` (up to {MAX_TEAMS}) to see more."
        )
    )


async def list_teams(client: GraphServiceClient, *, limit: int) -> TeamList:
    """Return up to `limit` teams."""
    assert 1 <= limit <= MAX_TEAMS, f"limit must be within 1..{MAX_TEAMS}, got {limit}"

    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.me.joined_teams.get()
        assert first_page is not None, "Graph answered GET /me/joinedTeams with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return TeamList(teams=[TeamSummary.from_team(team) for team in collected.items])


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Register this tool. The tool borrows `transport` per call."""
    # Built here because this is where `transport` is: the dependency closes over it, and the
    # default below is evaluated when the `def` runs, inside this call. The default holds a name,
    # not a call. A call there is ruff's B008.
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
