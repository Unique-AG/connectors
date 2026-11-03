import os
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from model import Context, Step

if TYPE_CHECKING:
    from seed import Graph

TAG = "seed-v1"
CASE_MARK = f"{TAG} case-"
TEAM_NAME = f"{TAG} team"
PHASES: tuple[str, ...] = ("teams", "teams-posts", "teams-chats")
OPT_IN = PHASES
UNSUPPORTED = (400, 403, 404, 405, 501)
OWNER = "mia"
WITH_PRIVATE = os.environ.get("SEED_TEAMS_PRIVATE", "1") != "0"
ANNA_AS = os.environ.get("SEED_TEAMS_ANNA_AS", "anna")
MEMBER = "#microsoft.graph.aadUserConversationMember"
CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "teams.yaml"
SPEC: Mapping[str, Any] = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
STRINGS: tuple[str, ...] = tuple(line for lines in SPEC["transcript"].values() for line in lines)
CHANNELS: Mapping[str, str] = {one["key"]: one["name"] for one in SPEC["channels"]}
NAMED = (("$select", "id,displayName"),)
PAGE = (("$top", "50"),)

type Message = Mapping[str, Any]
type Wanted = Callable[[Message, Message], bool]


def _ref(phase: str, name: str) -> str:
    return f"{{{phase}:{name}}}"


def _upn(ctx: Context, who: str) -> str:
    return ctx.upns[ctx.corpus["personas"]["personas"][who]["index"] - 1]


def _member(address: str, roles: list[str]) -> dict[str, object]:
    return {
        "@odata.type": MEMBER,
        "roles": roles,
        "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{address}')",
    }


def _channel_body(ctx: Context, channel: Mapping[str, Any]) -> dict[str, object]:
    if not channel.get("private"):
        return {"displayName": channel["name"], "membershipType": "standard"}
    return {
        "@odata.type": "#Microsoft.Graph.channel",
        "displayName": channel["name"],
        "membershipType": "private",
        "members": [
            _member(_upn(ctx, "mia"), ["owner"]),
            _member(_upn(ctx, "anna"), ["member"]),
        ],
    }


def _team_steps(ctx: Context) -> list[Step]:
    channels = f"/teams/{_ref('teams', TEAM_NAME)}/channels"
    members = f"/groups/{_ref('teams', TEAM_NAME)}/members"
    body = {
        "template@odata.bind": "https://graph.microsoft.com/v1.0/teamsTemplates('standard')",
        "displayName": TEAM_NAME,
        "description": "The team of the recorder cases.",
        "members": [_member(ctx.upns[0], ["owner"])],
    }
    return [
        Step("teams", "lookup", "GET", "/me/joinedTeams", NAMED, lookup="named", learns="team"),
        Step(
            "teams",
            "create",
            "POST",
            "/teams",
            body=body,
            key=f"teams:{TEAM_NAME}",
            poll=True,
            learns="team",
        ),
        Step("teams", "lookup", "GET", channels, NAMED, lookup="named"),
        Step(
            "teams",
            "lookup",
            "GET",
            members,
            (("$select", "id,userPrincipalName"),),
            lookup="members",
        ),
        *(
            Step(
                "teams",
                "create",
                "POST",
                f"{members}/$ref",
                body={"@odata.id": f"https://graph.microsoft.com/v1.0/users/{address}"},
                key=f"member:{address.lower()}",
            )
            for address in ctx.upns[1:]
        ),
        *(
            Step(
                "teams",
                "create",
                "POST",
                channels,
                body=_channel_body(ctx, one),
                key=f"teams:{one['name']}",
            )
            for one in SPEC["channels"]
            if WITH_PRIVATE or not one.get("private")
        ),
    ]


def _author(who: str) -> str:
    return ANNA_AS if who == "anna" else who


def threads() -> list[Message]:
    long = SPEC["long"]
    cycle = long["authors"]
    made = [
        {
            "id": f"l{n:02d}",
            "channel": "long",
            "author": _author(cycle[(n - 1) % len(cycle)]),
            "text": long["text"].format(n=n),
        }
        for n in range(1, long["count"] + 1)
    ]
    kept = [
        {**one, "author": _author(one["author"])}
        for one in SPEC["threads"]
        if WITH_PRIVATE or one["channel"] != "private"
    ]
    return [*kept, *made]


def replies_of(thread: Message) -> list[Message]:
    spec = thread.get("replies", [])
    if isinstance(spec, list):
        return [{**one, "author": _author(one["author"])} for one in spec]
    return [
        {"author": _author(spec["author"]), "text": spec["text"].format(n=n)}
        for n in range(1, spec["count"] + 1)
    ]


def post_subject(thread: Message) -> str:
    return f"{TAG} post {thread['id']}"


def _text_body(text: str, subject: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"body": {"contentType": "text", "content": text}}
    return {"subject": subject, **body} if subject else body


def _reply_steps(
    phase: str, thread: Message, root: str, owner: str
) -> tuple[list[Step], list[Step]]:
    path = f"{root}/replies"
    probe = f"replies:{thread['id']}"
    mine = [
        (f"reply:{probe}:{reply['text']}", reply)
        for reply in replies_of(thread)
        if reply["author"] == owner
    ]
    guards = [Step(phase, "lookup", "GET", path, lookup="replies", key=probe)]
    creates = [
        Step(phase, "create", "POST", path, body=_text_body(reply["text"]), key=key)
        for key, reply in mine
    ]
    return guards, creates


def _post_steps(owner: str) -> list[Step]:
    phase = "teams-posts"
    team = _ref(phase, TEAM_NAME)

    def messages(channel: str) -> str:
        return f"/teams/{team}/channels/{_ref(phase, CHANNELS[channel])}/messages"

    lookups = [
        Step(phase, "lookup", "GET", "/me/joinedTeams", NAMED, lookup="named", learns="team"),
        Step(phase, "lookup", "GET", f"/teams/{team}/channels", NAMED, lookup="named"),
        *(
            Step(phase, "lookup", "GET", messages(one["key"]), PAGE, lookup="subject")
            for one in SPEC["channels"]
        ),
    ]
    guards: list[Step] = []
    creates: list[Step] = []
    for thread in threads():
        subject = post_subject(thread)
        root = f"{messages(thread['channel'])}/{_ref('subject', subject)}"
        if thread["author"] == owner:
            body = _text_body(thread["text"], subject)
            path = messages(thread["channel"])
            creates.append(Step(phase, "create", "POST", path, body=body, key=f"subject:{subject}"))
        if any(reply["author"] == owner for reply in replies_of(thread)):
            more_guards, more_creates = _reply_steps(phase, thread, root, owner)
            guards += more_guards
            creates += more_creates
    return [*lookups, *guards, *creates]


def _chat_steps(ctx: Context, owner: str) -> list[Step]:
    phase = "teams-chats"
    lookups = [Step(phase, "lookup", "GET", "/me/chats", PAGE, lookup="named", learns="chat")]
    creates: list[Step] = []
    for chat in SPEC["chats"]:
        path = f"/chats/{_ref(phase, chat['topic'])}/messages"
        if chat["owner"] == owner:
            body = {
                "chatType": "group",
                "topic": chat["topic"],
                "members": [_member(_upn(ctx, who), ["owner"]) for who in chat["members"]],
            }
            key = f"{phase}:{chat['topic']}"
            creates.append(
                Step(phase, "create", "POST", "/chats", body=body, key=key, learns="chat")
            )
        mine = [one for one in chat["messages"] if one["author"] == owner]
        if mine:
            lookups.append(Step(phase, "lookup", "GET", path, PAGE, lookup="subject"))
        for one in mine:
            subject = f"{TAG} chat {one['id']}"
            body = _text_body(one["text"], subject)
            creates.append(Step(phase, "create", "POST", path, body=body, key=f"subject:{subject}"))
    return [*lookups, *creates]


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    return [
        *(_team_steps(ctx) if "teams" in phases and owner == OWNER else []),
        *(_post_steps(owner) if "teams-posts" in phases else []),
        *(_chat_steps(ctx, owner) if "teams-chats" in phases else []),
    ]


def _is_mine(message: Message, me: str | None) -> bool:
    return ((message.get("from") or {}).get("user") or {}).get("id") == me


def _wanted_here(message: Message, me: str | None) -> bool:
    return _is_mine(message, me) and not message.get("deletedDateTime")


def _pages(graph: Graph, path: str, params: Mapping[str, str]) -> list[Message]:
    found: list[Message] = []
    answer = graph.request("GET", path, params=params, ok_statuses=UNSUPPORTED)
    while answer.status_code == 200:
        page = answer.json()
        found += page.get("value", [])
        link = page.get("@odata.nextLink")
        if not link:
            break
        answer = graph.request("GET", link, ok_statuses=UNSUPPORTED)
    return found


def _channel_deletions(graph: Graph, wanted: Wanted) -> Iterator[tuple[str, str]]:
    for team in _pages(graph, "/me/joinedTeams", dict(NAMED)):
        if team.get("displayName") != TEAM_NAME:
            continue
        graph.learn("team", str(team["id"]))
        for channel in _pages(graph, f"/teams/{team['id']}/channels", {"$select": "id"}):
            base = f"/teams/{team['id']}/channels/{channel['id']}/messages"
            for root in _pages(graph, base, {"$top": "50", "$expand": "replies"}):
                found = [
                    (f"{base}/{root['id']}", root),
                    *(
                        (f"{base}/{root['id']}/replies/{r['id']}", r)
                        for r in root.get("replies", [])
                    ),
                ]
                for path, message in found:
                    if _wanted_here(message, graph.me_id) and wanted(message, root):
                        yield "POST", f"{path}/softDelete"


def _chat_deletions(graph: Graph, wanted: Wanted) -> Iterator[tuple[str, str]]:
    for chat in _pages(graph, "/me/chats", {"$select": "id,topic", "$top": "50"}):
        if not str(chat.get("topic") or "").startswith(f"{TAG} "):
            continue
        graph.learn("chat", str(chat["id"]))
        for message in _pages(graph, f"/chats/{chat['id']}/messages", dict(PAGE)):
            if _wanted_here(message, graph.me_id) and wanted(message, message):
                path = f"/users/{graph.me_id}/chats/{chat['id']}/messages/{message['id']}"
                yield "POST", f"{path}/softDelete"


def _seed_post(message: Message, root: Message) -> bool:
    return str(root.get("subject") or "").startswith(f"{TAG} post ")


def _seed_chat(message: Message, root: Message) -> bool:
    return str(message.get("subject") or "").startswith(f"{TAG} chat ")


def _case(message: Message, root: Message) -> bool:
    return CASE_MARK in str((message.get("body") or {}).get("content") or "")


def cleanup(
    graph: Graph, ctx: Context, owner: str, phases: set[str]
) -> Iterator[tuple[str, str, None]]:
    if "teams-posts" in phases:
        yield from ((method, path, None) for method, path in _channel_deletions(graph, _seed_post))
    if "teams-chats" in phases:
        yield from ((method, path, None) for method, path in _chat_deletions(graph, _seed_chat))


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str]]:
    answer = graph.request(
        "GET",
        "/me/onlineMeetings",
        params={"$select": "id,subject", "$top": "100"},
        ok_statuses=UNSUPPORTED,
    )
    if answer.status_code == 200:
        for meeting in answer.json().get("value", []):
            if CASE_MARK in (meeting.get("subject") or ""):
                yield "DELETE", f"/me/onlineMeetings/{meeting['id']}"
    yield from _channel_deletions(graph, _case)
    yield from _chat_deletions(graph, _case)
