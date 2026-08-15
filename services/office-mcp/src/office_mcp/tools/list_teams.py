"""`list_teams` — the teams the signed-in user is a member of.

The first step into the channel side of Teams, which `list_chats` does not cover at all: a chat is a
conversation the user is *in*, a channel is one they can *browse*, and nothing reaches a channel
without first naming the team it lives in. So this tool answers one question — which teams am I in —
and its `team_id` is the id `search_messages` already reports on every channel message it finds.

**Graph accepts no OData query parameter on this collection at all.** "This method doesn't currently
support the OData query parameters" (https://learn.microsoft.com/en-us/graph/api/user-list-joinedteams)
is the whole of the contract: no `$top`, no `$select`, no `$filter`, and no documented order.
`services/teams-mcp` shipped a `$top` here and had to take it back out ("drop unsupported $top on
joinedTeams and channels lists"), so sending one is a 400 rather than a narrower answer — which is
why this tool sends no request configuration whatever and applies its window while walking the pages
Graph chose. Only `id`, `displayName`, `description`, `isArchived` and `tenantId` come back
populated on this endpoint; every other property of a team is null whether or not it is asked for,
so no member count, no channel list and no activity date is claimed here.

What this file does not own is the token and the refusal wording (`shared/seam.py`, so this tool's
403 sounds like every other tool's). Everything else — the name, the description, the permission,
the window, the answer shape and the request — is here. In particular the window's bound is this
tool's own and stays this tool's own: a page size is not shared vocabulary, because a second
collection agreeing about a number is free to stop agreeing without either tool being wrong.
"""

from typing import Annotated

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.team import Team
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import collect_pages, graph_client_for, graph_errors
from office_mcp.shared.seam import READ_ONLY, graph_token, graph_tool_errors

TOOL_NAME = "list_teams"

# The delegated Graph permission this tool's one request needs — the cheap "basic" scope over a
# team's identity, which is all this collection returns. The registry unions every tool's, which is
# what sign-in asks Entra to consent to, and a refusal is worded from this same tuple.
GRAPH_PERMISSIONS: tuple[str, ...] = ("Team.ReadBasic.All",)

# Built once at import: a call inside a parameter default rebuilds the descriptor on every
# registration and is a lint error in both of this repo's checkers.
_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

# How many teams one call returns, and the ceiling on `limit`. Graph takes no `$top` on this
# collection, so this window is this connector's own and so is its bound: it exists to cap the
# number of Graph requests one call can make while walking the pages, not because Graph would refuse
# a larger one.
MAX_TEAMS = 200

_DESCRIPTION = f"""\
List the Microsoft Teams teams the signed-in user is a member of, with each team's id, name, \
description and archived flag.

This is the channel side of Teams, which list_chats does not cover at all: a chat is a \
conversation the user is *in*, a channel is one they can *browse*, and nothing reaches a channel \
without first naming the team it lives in. It answers "which teams am I in" and nothing more — no \
channels, no members, no messages, and no activity date, because Microsoft Graph populates none of \
those on this collection whether or not they are asked for. The `team_id` it returns is for \
*naming*: it is the same id search_messages reports on a channel message, so this list is how a \
hit from a channel gets a team name. No tool here takes a team id as an argument.

`is_archived` marks a team that is read-only in Teams, which usually means finished; together with \
`description` it is what tells apart two teams sharing a display name. Teams that merely host a \
shared channel the user belongs to are not listed — Microsoft returns only teams the user is a \
member of.

There is no pagination and no ordering: Microsoft Graph accepts no page size on this collection, \
and applies no order to it, so `limit` is a window over whatever order it answered in. As many \
teams as `limit` means the user may be in more; fewer than `limit` is all of them. Widen `limit` \
(up to {MAX_TEAMS}) rather than looking for a cursor.\
"""


class TeamSummary(BaseModel):
    team_id: str = Field(
        description=(
            "The team's Graph id. It is the same id search_messages reports as `team_id` on a "
            + "channel message, which is how a hit from a channel gets a team name. Opaque — copy "
            + "it, never build one from a team's name."
        )
    )
    display_name: str | None = Field(
        description="The team's name as Teams shows it. Two teams may share one."
    )
    description: str | None = Field(
        description=(
            "What the team is for, as its owners wrote it. Null when nobody wrote one, which is "
            + "common."
        )
    )
    is_archived: bool | None = Field(
        description=(
            "True for a team that has been archived, which in Teams means read-only and usually "
            + "means finished. Null when Microsoft Graph did not say. Together with `description` "
            + "this is what tells two teams with the same name apart."
        )
    )


class TeamList(BaseModel):
    teams: list[TeamSummary] = Field(
        description=(
            "The teams the signed-in user is a member of. As many as `limit` means there may be "
            + "more; fewer than `limit` is all of them, because the walk follows Microsoft's "
            + "paging to the end of the collection. There is no cursor: raise `limit` (up to "
            + f"{MAX_TEAMS}) to widen the window. Microsoft Graph applies no order here, so the "
            + "teams beyond a full window are an arbitrary rest rather than the least important "
            + "ones."
        )
    )


async def list_teams(client: GraphServiceClient, *, limit: int) -> TeamList:
    """The teams the signed-in user is a member of, up to `limit`.

    No request configuration at all: `/me/joinedTeams` accepts no OData query parameters, so a
    `$top` or a `$select` here is a 400 rather than a narrower answer. The window is therefore
    applied while walking the pages Graph chose.
    """
    assert 1 <= limit <= MAX_TEAMS, f"limit must be within 1..{MAX_TEAMS}, got {limit}"

    with graph_errors():
        first_page = await client.me.joined_teams.get()
        assert first_page is not None, "Graph answered GET /me/joinedTeams with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return TeamList(teams=[_team(team) for team in collected.items])


def _team(team: Team) -> TeamSummary:
    assert team.id is not None, "Graph returned a joined team with no id"
    return TeamSummary(
        team_id=team.id,
        display_name=team.display_name,
        description=team.description,
        is_archived=team.is_archived,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this tool against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tool
    borrows it per call and never owns it. `create_app` closes it on shutdown.
    """

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
                    "How many teams to return. Default 50, maximum "
                    + f"{MAX_TEAMS} — Microsoft Graph applies no page size to this "
                    + "collection, so this is a window this connector applies while paging it."
                ),
            ),
        ] = 50,
        graph_token: str = _TOKEN,
    ) -> TeamList:
        with graph_tool_errors(*GRAPH_PERMISSIONS):
            return await list_teams(graph_client_for(transport, graph_token), limit=limit)
