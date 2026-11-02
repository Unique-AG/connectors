"""Offline tests for the teams seed plug-in, against an in-memory Teams."""

import datetime as dt
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed
from families import teams
from model import ConfigError, Context
from test_seed import UPNS

TEAM = "11111111-2222-4333-8444-555555555555"
OPERATION = f"/teams('{TEAM}')/operations('66666666-7777-4888-8999-000000000000')"
PHASES = {"teams", "teams-posts", "teams-chats"}
PERSONAS = ("mia", "anna", "tom")
POSTS, LONG, PRIVATE = "seed-v1 Posts", "seed-v1 Long channel", "seed-v1 Private"


class TeamsGraph:
    def __init__(self) -> None:
        self.me = "mia"
        self.team: str | None = None
        self.channels: dict[str, dict[str, Any]] = {}
        self.chats: dict[str, dict[str, Any]] = {}
        self.count = 0

    def new_id(self, prefix: str) -> str:
        self.count += 1
        return f"{prefix}-{self.count}"

    def page(self, request: httpx.Request, items: list[dict[str, Any]]) -> httpx.Response:
        start = int(request.url.params.get("skip", "0"))
        size = int(request.url.params.get("$top", "50"))
        body: dict[str, Any] = {"value": items[start : start + size]}
        if start + size < len(items):
            link = request.url.copy_merge_params({"skip": str(start + size)})
            body["@odata.nextLink"] = str(link)
        return httpx.Response(200, json=body)

    def message(self, body: dict[str, Any]) -> dict[str, Any]:
        made = {"id": self.new_id("m"), "replies": [], "deletedDateTime": None, **body}
        return {**made, "from": {"user": {"id": f"id-{self.me}"}}}

    def visible(self) -> dict[str, dict[str, Any]]:
        return {key: one for key, one in self.channels.items() if self.me in one["members"]}

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0")
        method = request.method
        body = json.loads(request.content) if request.content else {}
        if method == "POST" and path == "/teams":
            headers = {"location": OPERATION, "content-location": f"/teams('{TEAM}')"}
            return httpx.Response(202, headers=headers)
        if path == OPERATION:
            self.team = TEAM
            general = {"displayName": "General", "members": PERSONAS}
            self.channels = {"general": {"id": "general", **general, "posts": []}}
            return httpx.Response(200, json={"status": "succeeded"})
        if path == "/me/joinedTeams":
            held = [{"id": self.team, "displayName": teams.TEAM_NAME}] if self.team else []
            return self.page(request, held)
        if path == "/me/onlineMeetings":
            return httpx.Response(404)
        return self.handle_content(request, path, method, body)

    def handle_content(
        self, request: httpx.Request, path: str, method: str, body: dict[str, Any]
    ) -> httpx.Response:
        if path == f"/teams/{TEAM}/channels":
            if method == "POST":
                members = [PERSONAS[0], PERSONAS[1]] if body.get("members") else PERSONAS
                made = {"id": self.new_id("c"), "displayName": body["displayName"]}
                self.channels[made["id"]] = {**made, "members": members, "posts": []}
                return httpx.Response(201, json=made)
            return self.page(request, list(self.visible().values()))
        if method == "POST" and path.endswith("/softDelete"):
            self.soft_delete(path.rsplit("/", 2)[-2])
            return httpx.Response(204)
        if found := re.fullmatch(rf"/teams/{TEAM}/channels/([^/]+)/messages", path):
            posts = self.channels[found[1]]["posts"]
            if method == "POST":
                posts.append(self.message(body))
                return httpx.Response(201, json=posts[-1])
            return self.page(request, posts)
        found = re.fullmatch(
            rf"/teams/{TEAM}/channels/([^/]+)/messages/([^/]+)/replies(?:/(.+))?", path
        )
        if found:
            post = next(p for p in self.channels[found[1]]["posts"] if p["id"] == found[2])
            if method == "POST":
                post["replies"].append(self.message(body))
                return httpx.Response(201, json=post["replies"][-1])
            if found[3]:
                held = any(r["id"] == found[3] for r in post["replies"])
                return httpx.Response(200 if held else 404, json={"id": found[3]})
            return self.page(request, post["replies"])
        return self.handle_chats(request, path, method, body)

    def handle_chats(
        self, request: httpx.Request, path: str, method: str, body: dict[str, Any]
    ) -> httpx.Response:
        if path == "/me/chats":
            mine = [c for c in self.chats.values() if self.me in c["members"]]
            return self.page(request, mine)
        if method == "POST" and path == "/chats":
            members = [self.who(m["user@odata.bind"]) for m in body["members"]]
            made = {"id": self.new_id("chat"), "topic": body["topic"], "members": members}
            self.chats[made["id"]] = {**made, "posts": []}
            return httpx.Response(201, json=made)
        if found := re.fullmatch(r"/chats/([^/]+)/messages", path):
            posts = self.chats[found[1]]["posts"]
            if method == "POST":
                posts.append(self.message(body))
                return httpx.Response(201, json=posts[-1])
            return self.page(request, posts)
        raise AssertionError(f"{method} {path} is not a call that the seed makes")

    def soft_delete(self, identifier: str) -> None:
        wrappers = [*self.channels.values(), *self.chats.values()]
        for one in wrappers:
            for post in one["posts"]:
                for message in (post, *post.get("replies", [])):
                    if message["id"] == identifier:
                        message["deletedDateTime"] = "2026-10-30T00:00:00Z"

    @staticmethod
    def who(bound: str) -> str:
        return next(name for name, upn in zip(PERSONAS, UPNS, strict=True) if upn in bound)

    def run(self, who: str, steps: list[Any], ctx: Context) -> tuple[int, int]:
        self.me = who
        graph = real_graph(self, who)
        seed.check_recipients(steps, UPNS)
        return seed.apply(graph, steps, ctx, lambda _: None)


def context() -> Context:
    return Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, dt.date(2026, 10, 23), "extprops")


def seeded() -> TeamsGraph:
    fake = TeamsGraph()
    for who in PERSONAS:
        fake.run(who, teams.steps(context(), who, PHASES), context())
    return fake


def titles(posts: list[dict[str, Any]]) -> list[str]:
    return [p["subject"] for p in posts]


def test_only_mia_creates_the_team_and_only_when_the_phase_is_on() -> None:
    assert teams.PHASES == ("teams", "teams-posts", "teams-chats")
    assert teams.steps(context(), "anna", {"teams"}) == []
    assert teams.steps(context(), "tom", {"teams"}) == []
    assert teams.steps(context(), "mia", {"mail"}) == []
    lookup, create, channels, *made = teams.steps(context(), "mia", {"teams"})
    assert (lookup.method, lookup.path, lookup.lookup) == ("GET", "/me/joinedTeams", "named")
    assert (create.method, create.path, create.poll) == ("POST", "/teams", True)
    assert create.key == f"teams:{teams.TEAM_NAME}" == "teams:seed-v1 team"
    assert (channels.path, channels.lookup) == ("/teams/{teams:seed-v1 team}/channels", "named")
    assert [step.key for step in made] == [f"teams:{one}" for one in (POSTS, LONG, PRIVATE)]
    assert {lookup.learns, create.learns} == {"team"}


def test_the_team_starts_with_its_owner_only_because_graph_takes_one_member() -> None:
    steps = teams.steps(context(), "mia", {"teams"})
    seed.check_recipients(steps, UPNS)
    bound = {m["user@odata.bind"]: m["roles"] for m in steps[1].body["members"]}
    assert bound == {f"https://graph.microsoft.com/v1.0/users('{UPNS[0]}')": ["owner"]}
    assert steps[1].body["displayName"] == "seed-v1 team"


def test_the_private_channel_has_mia_as_owner_and_anna_as_member_and_not_tom() -> None:
    private = teams.steps(context(), "mia", {"teams"})[-1].body
    assert private["membershipType"] == "private"
    bound = {m["user@odata.bind"]: m["roles"] for m in private["members"]}
    assert bound == {
        f"https://graph.microsoft.com/v1.0/users('{UPNS[0]}')": ["owner"],
        f"https://graph.microsoft.com/v1.0/users('{UPNS[1]}')": ["member"],
    }


def test_the_personas_in_order_seed_the_team_once_and_a_second_run_creates_nothing() -> None:
    fake = TeamsGraph()
    for who in PERSONAS:
        fake.run(who, teams.steps(context(), who, PHASES), context())
    names = {one["displayName"] for one in fake.channels.values()}
    assert names == {"General", POSTS, LONG, PRIVATE}
    by_name = {one["displayName"]: one for one in fake.channels.values()}
    assert len(by_name[POSTS]["posts"]) == 7
    assert len(by_name[LONG]["posts"]) == 60
    assert len(by_name[PRIVATE]["posts"]) == 2
    replies = {p["subject"]: len(p["replies"]) for p in by_name[POSTS]["posts"]}
    assert replies == {
        "seed-v1 post p01": 2,
        "seed-v1 post p02": 3,
        "seed-v1 post p03": 0,
        "seed-v1 post p04": 1,
        "seed-v1 post p05": 0,
        "seed-v1 post p06": 0,
        "seed-v1 post t51": 51,
    }
    unread = next(c for c in fake.chats.values() if "unread" in c["topic"])
    send = next(c for c in fake.chats.values() if "send" in c["topic"])
    assert (len(unread["posts"]), len(send["posts"])) == (5, 1)
    before = (len(fake.channels), len(fake.chats), fake.count)
    again = [fake.run(who, teams.steps(context(), who, PHASES), context()) for who in PERSONAS]
    assert [created for created, _ in again] == [0, 0, 0]
    assert (len(fake.channels), len(fake.chats), fake.count) == before


def test_each_persona_posts_only_as_that_persona_and_tom_never_reaches_the_private_channel() -> (
    None
):
    fake = seeded()
    by_name = {one["displayName"]: one for one in fake.channels.values()}
    long = by_name[LONG]["posts"]
    assert [sum(p["from"]["user"]["id"] == f"id-{w}" for p in long) for w in PERSONAS] == [20] * 3
    assert {p["from"]["user"]["id"] for p in by_name[PRIVATE]["posts"]} == {"id-mia", "id-anna"}
    thread = next(p for p in by_name[POSTS]["posts"] if p["subject"].endswith("t51"))
    assert {r["from"]["user"]["id"] for r in thread["replies"]} == {"id-anna"}
    anna = teams.steps(context(), "tom", PHASES)
    assert not [s for s in anna if teams.CHANNELS["private"] in s.path and s.kind == "create"]


def test_a_reply_before_its_post_stops_the_run_and_names_the_missing_item() -> None:
    fake = TeamsGraph()
    fake.run("mia", teams.steps(context(), "mia", {"teams"}), context())
    with pytest.raises(ConfigError, match="run the earlier phase first"):
        fake.run("anna", teams.steps(context(), "anna", {"teams-posts"}), context())


def test_every_thread_has_one_replier_who_comes_after_the_author() -> None:
    for thread in teams.threads():
        authors = {reply["author"] for reply in teams.replies_of(thread)}
        assert len(authors) <= 1
        assert not authors or PERSONAS.index(authors.pop()) > PERSONAS.index(thread["author"])


def test_a_chat_stays_unread_for_mia_because_she_never_writes_in_it() -> None:
    unread = next(c for c in teams.SPEC["chats"] if c["key"] == "unread")
    assert {m["author"] for m in unread["messages"]} == {"anna", "tom"}
    assert unread["topic"].startswith(teams.CASE_MARK)


def test_a_seed_text_holds_the_words_that_the_search_cases_use_and_no_case_mark() -> None:
    texts = [t["text"] for t in teams.threads()]
    texts += [r["text"] for t in teams.threads() for r in teams.replies_of(t)]
    texts += [m["text"] for c in teams.SPEC["chats"] for m in c["messages"]]
    assert sum("Alpine Print" in one for one in texts) == 3
    assert sum("Lena Fischer" in one for one in texts) == 2
    assert not [one for one in texts if teams.CASE_MARK in one]


def test_the_manifest_holds_every_post_every_reply_and_every_transcript_line() -> None:
    held = set(seed.corpus_manifest(context())["strings"])
    assert "Anna sends the budget file by Friday." in held
    assert "Note 51 of the long thread." in held
    assert "Long channel note 60. The weekly status is green." in held
    assert "seed-v1 post t51" in held
    assert set(teams.STRINGS) <= held


def real_graph(fake: TeamsGraph, who: str) -> seed.Graph:
    fake.me = who
    transport = httpx.MockTransport(fake.handle)
    graph = seed.Graph("tok", transport=transport, sleep=lambda _: None)
    graph.me_id = f"id-{who}"
    return graph


def test_the_cleanup_of_a_phase_names_the_seed_posts_of_the_signed_in_persona_only() -> None:
    fake = seeded()
    graph = real_graph(fake, "anna")
    gone = list(teams.cleanup(graph, context(), "anna", {"teams-posts"}))
    assert len(gone) == 23 + 53
    assert {method for method, _, _ in gone} == {"POST"}
    assert all(path.endswith("/softDelete") for _, path, _ in gone)
    assert len([p for _, p, _ in gone if "/replies/" in p]) == 53
    assert list(teams.cleanup(graph, context(), "anna", {"teams"})) == []
    assert len(list(teams.cleanup(graph, context(), "anna", {"teams-chats"}))) == 3
    assert len(list(teams.cleanup(real_graph(fake, "tom"), context(), "tom", {"teams-chats"}))) == 2


def test_the_cleanup_runs_through_seed_and_a_second_run_finds_nothing_left_to_delete() -> None:
    fake = seeded()
    graph = real_graph(fake, "mia")
    phases = {"teams-posts", "teams-chats"}
    assert seed.cleanup(graph, context(), 1, phases, True, print) == 24 + 1
    assert seed.cleanup(graph, context(), 1, phases, False, print) == 24 + 1
    assert seed.cleanup(graph, context(), 1, phases, False, print) == 0
    anna = real_graph(fake, "anna")
    assert len(list(teams.cleanup(anna, context(), "anna", {"teams-posts"}))) == 23 + 53


def test_the_sweep_names_a_message_that_holds_the_case_mark_and_the_meetings_of_a_case() -> None:
    fake = seeded()
    graph = real_graph(fake, "anna")
    own = fake.message({"subject": None, "body": {"content": "seed-v1 case-x hello"}})
    next(c for c in fake.channels.values() if c["displayName"] == POSTS)["posts"].append(own)
    other = {**own, "id": "m-other", "from": {"user": {"id": "id-tom"}}}
    next(c for c in fake.channels.values() if c["displayName"] == POSTS)["posts"].append(other)
    chat = next(c for c in fake.chats.values() if "send" in c["topic"])
    chat["posts"].append(fake.message({"body": {"content": "seed-v1 case-y mention"}}))
    swept = list(teams.sweep(graph, "anna"))
    assert [path.rsplit("/", 2)[-2] for _, path in swept] == [own["id"], chat["posts"][-1]["id"]]
    assert all(method == "POST" for method, _ in swept)


class Meetings:
    def __init__(self, status: int, meetings: list[dict[str, str | None]]) -> None:
        self.status = status
        self.meetings = meetings
        self.me_id = "id"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        ok_statuses: tuple[int, ...] = (),
    ) -> SimpleNamespace:
        assert method == "GET"
        if path != "/me/onlineMeetings":
            return SimpleNamespace(status_code=200, json=lambda: {"value": []})
        assert self.status == 200 or self.status in ok_statuses
        return SimpleNamespace(status_code=self.status, json=lambda: {"value": self.meetings})

    def learn(self, kind: str, identifier: str) -> None:
        return None


def test_the_sweep_names_only_the_meetings_of_a_case() -> None:
    graph = Meetings(
        200,
        [
            {"id": "m1", "subject": "seed-v1 case-teams_create_meeting-solo meeting"},
            {"id": "m2", "subject": "Weekly sync"},
            {"id": "m3", "subject": None},
        ],
    )
    assert list(teams.sweep(graph, "mia")) == [("DELETE", "/me/onlineMeetings/m1")]  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("status", teams.UNSUPPORTED)
def test_the_sweep_ends_quietly_where_graph_lists_no_meetings(status: int) -> None:
    graph = Meetings(status, [{"id": "m1", "subject": "seed-v1 case-x"}])
    assert list(teams.sweep(graph, "anna")) == []  # pyright: ignore[reportArgumentType]


class Forbidden:
    me_id = "id"

    def request(self, method: str, path: str, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(status_code=403, json=lambda: {})

    def learn(self, kind: str, identifier: str) -> None:
        return None


def test_a_cleanup_that_graph_refuses_names_nothing_and_stops_quietly() -> None:
    graph = Forbidden()
    assert list(teams.cleanup(graph, context(), "tom", PHASES)) == []  # pyright: ignore[reportArgumentType]
    assert list(teams.sweep(graph, "tom")) == []  # pyright: ignore[reportArgumentType]
