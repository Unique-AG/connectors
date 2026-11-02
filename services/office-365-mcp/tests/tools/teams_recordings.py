from collections.abc import Mapping
from typing import cast

import respx

from tests.tools.scenarios.support import call

type Row = Mapping[str, object]

ANNA: Row = {"user_id": "00000000-a6b4-4b6e-8a2b-9e1c3f1e88e1", "name": "Anna Meier"}
TOM: Row = {"user_id": "00000000-e469-40d3-8f5b-9a7c5dac541e", "name": "Tom Berger"}
GROUP_TOPIC = "seed-v1 case-teams-chat"
GROUP_MEMBERS = [ANNA, TOM]


def rows(result: Row, key: str) -> list[Row]:
    return cast("list[Row]", result[key])


async def new_group_chat() -> Row:
    return await call(
        "teams_create_chat", chat_type="group", topic=GROUP_TOPIC, members=GROUP_MEMBERS
    )


async def post_in_seed_channel(message: str) -> Row:
    teams = rows(await call("teams_list_my_teams"), "teams")
    team_id = next(team["team_id"] for team in teams if team["display_name"] == "seed-v1 team")
    channels = await call("teams_list_channels", team_id=team_id, membership_type="standard")
    return await call(
        "teams_send_channel_message",
        team_id=team_id,
        channel_id=rows(channels, "channels")[0]["channel_id"],
        message=message,
    )


def uncalled(routes: dict[tuple[str, str], respx.Route]) -> list[tuple[str, str]]:
    return [key for key, route in routes.items() if not route.called]


def was_sent(routes: dict[tuple[str, str], respx.Route], method: str, path_part: str) -> bool:
    return any(
        route.called
        for (verb, path), route in routes.items()
        if verb == method and path_part in path
    )
