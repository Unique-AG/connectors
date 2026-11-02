from collections.abc import Iterator
from typing import TYPE_CHECKING

from model import Context, Step

if TYPE_CHECKING:
    from seed import Graph

PHASES: tuple[str, ...] = ("teams",)
CASE_MARK = "seed-v1 case-"
TEAM_NAME = "seed-v1 team"
UNSUPPORTED = (400, 403, 404, 405, 501)
OWNER = "mia"
MEMBER = "#microsoft.graph.aadUserConversationMember"


def _member(address: str, roles: list[str]) -> dict[str, object]:
    return {
        "@odata.type": MEMBER,
        "roles": roles,
        "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{address}')",
    }


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    if "teams" not in phases or owner != OWNER:
        return []
    members = [_member(ctx.upns[0], ["owner"])]
    body = {
        "template@odata.bind": "https://graph.microsoft.com/v1.0/teamsTemplates('standard')",
        "displayName": TEAM_NAME,
        "description": "The team of the recorder cases.",
        "members": members,
    }
    params = (("$select", "id,displayName"),)
    return [
        Step("teams", "lookup", "GET", "/me/joinedTeams", params, lookup="named"),
        Step("teams", "create", "POST", "/teams", body=body, key=f"teams:{TEAM_NAME}", poll=True),
    ]


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str]]:
    answer = graph.request(
        "GET",
        "/me/onlineMeetings",
        params={"$select": "id,subject", "$top": "100"},
        ok_statuses=UNSUPPORTED,
    )
    if answer.status_code != 200:
        return
    for meeting in answer.json().get("value", []):
        if CASE_MARK in (meeting.get("subject") or ""):
            yield "DELETE", f"/me/onlineMeetings/{meeting['id']}"
