"""Offline tests for the seed family plug-ins."""

import datetime as dt
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed
from model import Context, Step
from test_seed import UPNS, FakeGraph, run

NOTES = Step("notes", "create", "POST", "/me/onenote/notebooks", body={"displayName": "x"})


def a_family(*, swept: list[tuple[str, str]]) -> SimpleNamespace:
    def sweep(graph: object, owner: str) -> Iterator[tuple[str, str]]:
        yield from swept

    return SimpleNamespace(PHASES=("notes",), steps=lambda ctx, owner, phases: [NOTES], sweep=sweep)


def test_the_stub_families_add_no_phase_and_no_step() -> None:
    stubs = [family for family in seed.FAMILIES if not family.PHASES]
    assert stubs
    assert seed.PHASES[:4] == ("folders", "mail", "events", "files")
    ctx = Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, dt.date(2026, 10, 23), "extprops")
    assert all(family.steps(ctx, "mia", set(seed.PHASES)) == [] for family in stubs)


def test_a_family_adds_its_steps_to_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "FAMILIES", (a_family(swept=[]),))
    ctx = Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, dt.date(2026, 10, 23), "extprops")
    assert seed.build_steps(ctx, 1, {"notes"})[-1] == NOTES


def test_cleanup_cases_deletes_only_what_the_sweep_names(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGraph()
    assert run(["apply", "--as", "1", "--phases", "files"], fake) == 0
    case = {"id": "case-1", "name": "seed-v1 case-x", "parent": "root", "folder": False}
    fake.drive["case-1"] = case
    fake.calls.clear()
    monkeypatch.setattr(seed, "FAMILIES", (a_family(swept=[("DELETE", "/me/drive/items/case-1")]),))
    assert run(["cleanup", "--cases", "--as", "1", "--dry-run"], fake) == 0
    assert ("DELETE", "/me/drive/items/case-1") not in fake.calls
    assert run(["cleanup", "--cases", "--as", "1"], fake) == 0
    assert ("DELETE", "/me/drive/items/case-1") in fake.calls
    assert "case-1" not in fake.drive
    assert len(fake.drive) > 1


def test_cases_applies_to_cleanup_only() -> None:
    assert run(["apply", "--cases", "--as", "1"], FakeGraph()) == seed.ConfigError.code


def test_a_named_lookup_finds_the_item_by_its_seed_name_so_the_second_run_creates_nothing() -> None:
    class Listing:
        def __init__(self) -> None:
            self.posts = 0

        def get_all(self, path: str, params: dict[str, str]) -> Iterator[dict[str, str]]:
            yield {"id": "n1", "displayName": "seed-v1 Notes"}
            yield {"id": "n2", "displayName": "someone else's notebook"}

        def request(self, *args: object, **kwargs: object) -> object:
            self.posts += 1
            raise AssertionError("a found item must not be created again")

    steps = [
        Step("onenote", "lookup", "GET", "/me/onenote/notebooks", lookup="named"),
        Step("onenote", "create", "POST", "/me/onenote/notebooks", key="onenote:seed-v1 Notes"),
    ]
    context = Context({}, UPNS, dt.date(2026, 1, 1), "mail")
    graph = Listing()
    created, skipped = seed.apply(graph, steps, context, lambda line: None)  # type: ignore[arg-type]
    assert (created, skipped, graph.posts) == (0, 1, 0)
