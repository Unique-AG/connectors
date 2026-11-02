"""Offline tests for the teams seed plug-in."""

import datetime as dt
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed
from families import teams
from model import Context
from test_seed import UPNS


class MeetingsGraph:
    def __init__(self, status: int, meetings: list[dict[str, str]]) -> None:
        self.status = status
        self.meetings = meetings
        self.asked: list[tuple[str, str, dict[str, str]]] = []

    def request(
        self, method: str, path: str, *, params: dict[str, str], ok_statuses: tuple[int, ...]
    ) -> SimpleNamespace:
        self.asked.append((method, path, params))
        assert self.status == 200 or self.status in ok_statuses
        return SimpleNamespace(status_code=self.status, json=lambda: {"value": self.meetings})


def context() -> Context:
    return Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, dt.date(2026, 10, 23), "extprops")


def test_only_mia_creates_the_team_and_only_when_the_phase_is_on() -> None:
    assert teams.PHASES == ("teams",)
    assert teams.steps(context(), "anna", set(seed.PHASES)) == []
    assert teams.steps(context(), "tom", set(seed.PHASES)) == []
    assert teams.steps(context(), "mia", {"mail"}) == []
    lookup, create = teams.steps(context(), "mia", {"teams"})
    assert (lookup.method, lookup.path, lookup.lookup) == ("GET", "/me/joinedTeams", "named")
    assert (create.method, create.path, create.poll) == ("POST", "/teams", True)
    assert create.key == f"teams:{teams.TEAM_NAME}" == "teams:seed-v1 team"


def test_the_team_starts_with_its_owner_only_because_graph_takes_one_member() -> None:
    create = teams.steps(context(), "mia", {"teams"})[1]
    seed.check_recipients([create], UPNS)
    bound = {m["user@odata.bind"]: m["roles"] for m in create.body["members"]}
    assert bound == {
        f"https://graph.microsoft.com/v1.0/users('{UPNS[0]}')": ["owner"],
    }
    assert create.body["displayName"] == "seed-v1 team"
    assert "seed-v1 team" in seed.corpus_manifest(context())["strings"]


def test_a_second_apply_finds_the_team_and_creates_nothing() -> None:
    class Listing:
        def __init__(self, held: list[dict[str, str]]) -> None:
            self.held, self.posts = held, 0

        def get_all(self, path: str, params: dict[str, str]) -> Iterator[dict[str, str]]:
            yield from self.held

        def request(self, *args: object, **kwargs: object) -> SimpleNamespace:
            self.posts += 1
            return SimpleNamespace(json=lambda: {"id": "unused"})

        def created_by_operation(self, response: object) -> dict[str, str]:
            return {"id": "new-team"}

    steps = teams.steps(context(), "mia", {"teams"})
    held = Listing([{"id": "t1", "displayName": "seed-v1 team"}])
    assert seed.apply(held, steps, context(), lambda _: None) == (0, 1)  # pyright: ignore[reportArgumentType]
    assert held.posts == 0
    empty = Listing([{"id": "t2", "displayName": "Other team"}])
    assert seed.apply(empty, steps, context(), lambda _: None) == (1, 0)  # pyright: ignore[reportArgumentType]
    assert empty.posts == 1


def test_the_sweep_names_only_the_meetings_of_a_case() -> None:
    graph = MeetingsGraph(
        200,
        [
            {"id": "m1", "subject": "seed-v1 case-teams_create_meeting-solo meeting"},
            {"id": "m2", "subject": "Weekly sync"},
            {"id": "m3", "subject": None},
        ],
    )
    assert list(teams.sweep(graph, "mia")) == [("DELETE", "/me/onlineMeetings/m1")]
    assert graph.asked == [("GET", "/me/onlineMeetings", {"$select": "id,subject", "$top": "100"})]


@pytest.mark.parametrize("status", teams.UNSUPPORTED)
def test_the_sweep_ends_quietly_where_graph_lists_no_meetings(status: int) -> None:
    graph = MeetingsGraph(status, [{"id": "m1", "subject": "seed-v1 case-x"}])
    assert list(teams.sweep(graph, "anna")) == []
