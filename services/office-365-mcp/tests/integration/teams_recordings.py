from collections.abc import Mapping, Sequence
from typing import cast

import respx

from tests.integration.conftest import JOIN_WEB_URL
from tests.integration.support import call

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


def aad_member(
    display_name: str, *, email: str | None = None, user_id: str | None = None
) -> dict[str, object]:
    member: dict[str, object] = {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "id": f"member-{display_name.replace(' ', '-').lower()}",
        "displayName": display_name,
        "email": email or f"{display_name.split()[0].lower()}@example.invalid",
    }
    if user_id is not None:
        member["userId"] = user_id
    return member


def chat_payload(
    chat_id: str,
    *,
    chat_type: str = "group",
    topic: str | None = "Release planning",
    last_message_at: str | None = "2026-02-11T09:15:22.31Z",
    members: Sequence[Mapping[str, object]] | None = None,
    online_meeting_info: Mapping[str, object] | None = None,
    preview: Mapping[str, object] | None = None,
    last_read_at: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": chat_id,
        "chatType": chat_type,
        "topic": topic,
        "createdDateTime": "2026-01-04T12:00:00Z",
        "lastUpdatedDateTime": "2026-02-11T09:15:22.31Z",
        "onlineMeetingInfo": dict(online_meeting_info) if online_meeting_info is not None else None,
        "members": list(members) if members is not None else [aad_member("Ada Lovelace")],
    }
    if last_message_at is not None:
        payload["lastMessagePreview"] = {
            "id": "1770000000000",
            "createdDateTime": last_message_at,
            "body": {"contentType": "text", "content": "synthetic preview"},
            **(preview or {}),
        }
    if last_read_at is not None:
        payload["viewpoint"] = {"isHidden": False, "lastMessageReadDateTime": last_read_at}
    return payload


def online_meeting_info(join_web_url: str | None = JOIN_WEB_URL) -> dict[str, object]:
    return {
        "calendarEventId": "AAMkAGSYNTHETIC",
        "joinWebUrl": join_web_url,
        "organizer": {
            "user": {
                "@odata.type": "#microsoft.graph.teamworkUserIdentity",
                "id": "00000000-0000-4000-8000-000000000002",
                "displayName": "Grace Hopper",
            }
        },
    }
