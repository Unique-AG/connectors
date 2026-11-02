"""Offline tests for the outlook-calendar seed family."""

import base64
import datetime as dt
import re
import sys
from collections.abc import Iterator, Mapping
from itertools import count
from pathlib import Path
from typing import Any

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed
from families import outlook_calendar as family
from model import Context, Step
from test_seed import UPNS

CASES = HERE.parents[2] / "tests/e2e/recording/cases/outlook-calendar.yaml"
ANCHOR = dt.date(2026, 10, 23)


class CalendarGraph:
    def __init__(self, held: Mapping[str, list[dict[str, Any]]] | None = None) -> None:
        self.items: dict[str, list[dict[str, Any]]] = {k: list(v) for k, v in (held or {}).items()}
        self.posts: list[str] = []
        self.ids = count(1)

    def get_all(self, path: str, params: Mapping[str, str]) -> Iterator[dict[str, Any]]:
        yield from self.items.get(path, [])

    def request(self, method: str, path: str, **kwargs: Any) -> CalendarGraph:
        body = kwargs.get("body") or {}
        self.posts.append(path)
        self.items.setdefault(path, []).append({"id": f"id{next(self.ids)}", **body})
        return self

    def json(self) -> dict[str, Any]:
        return {"id": f"id{next(self.ids) - 1}"}


def context() -> Context:
    return Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, ANCHOR, "extprops")


def plan(index: int, phases: set[str] | None = None) -> list[Step]:
    return [
        step
        for step in seed.build_steps(context(), index, phases or set(family.PHASES))
        if step.phase in family.PHASES
    ]


def test_the_family_adds_four_phases_to_the_seed() -> None:
    assert family.PHASES == ("cal-calendars", "cal-events", "cal-contacts", "cal-invites")
    assert set(family.PHASES) <= set(seed.PHASES)


def test_mia_gets_the_calendars_events_and_contacts_and_anna_the_invitation() -> None:
    mia, anna, tom = plan(1), plan(2), plan(3)
    created = [step.key for step in mia if step.kind == "create"]
    assert created == [
        "file:seed-v1 Shared calendar",
        "file:seed-v1 Spare calendar",
        *(f"event:c0{n}" for n in (1, 2, 3)),
        "file:calendar-agenda.txt",
        "event:c04",
        "event:c05",
        "contact:k01",
        "contact:k02",
        "event:a01",
    ]
    assert [step.key for step in anna if step.kind == "create"] == ["event:a01"]
    assert tom == []


def test_a_step_names_only_keys_that_an_earlier_step_makes() -> None:
    for index in (1, 2, 3):
        made: set[str] = set()
        for step in plan(index):
            assert set(re.findall(r"\{([^}]+)\}", step.path)) <= made
            made |= {step.key} if step.key else set()
            made |= {"subject:Roadmap check"} if step.lookup == "subject" else set()


def test_every_item_is_tagged_and_none_is_swept_before_a_case() -> None:
    for index in (1, 2):
        for step in (one for one in plan(index) if one.kind == "create"):
            assert "case-" not in repr(step.body)
            body = step.body
            if step.path.startswith("/me/calendars"):
                assert body["name"].startswith("seed-v1 ")
            elif step.path in {"/me/events", "/me/contacts"}:
                assert body["categories"] == ["seed-v1"]
                assert body["singleValueExtendedProperties"][0]["value"] == f"seed-v1:{step.key}"


def test_an_invitation_goes_to_a_persona_only() -> None:
    steps = plan(1) + plan(2)
    seed.check_recipients(steps, UPNS)
    people = [
        a["emailAddress"]["address"] for s in steps for a in (s.body or {}).get("attendees", [])
    ]
    assert sorted(people) == sorted([UPNS[1], UPNS[1], UPNS[0]])


def test_every_seed_text_reaches_the_corpus_manifest() -> None:
    strings = set(seed.corpus_manifest(context())["strings"])
    spec = family.SPEC
    wanted = [e["subject"] for e in spec["events"]] + [e["body"] for e in spec["events"]]
    wanted += [c["display_name"] for c in spec["contacts"]] + [
        c["company"] for c in spec["contacts"]
    ]
    wanted += [f"seed-v1 {c['name']}" for c in spec["calendars"]]
    wanted += [base64.b64encode(a["text"].encode()).decode() for a in spec["attachments"].values()]
    assert set(wanted) <= strings


def test_the_cases_read_the_seed_text_and_the_calendar_order() -> None:
    cases = yaml.safe_load(CASES.read_text())
    subjects = {e["subject"] for e in family.SPEC["events"]}
    listed = ["Calendar", *(f"seed-v1 {c['name']}" for c in family.SPEC["calendars"])]
    for case in cases.values():
        for step in case["chain"]:
            wanted = step.get("args", {}).get("subject_contains")
            assert wanted is None or wanted in subjects
            for path, name in step.get("expect", {}).get("result", {}).items():
                assert listed[int(re.search(r"\[(\d)\]", path)[1])] == name
        assert set(case.get("reseed", [])) <= set(seed.PHASES)


def test_apply_twice_creates_nothing_the_second_time() -> None:
    graph = CalendarGraph()
    steps = [step for step in plan(1) if step.phase != "cal-invites"]
    first = seed.apply(graph, steps, context(), lambda _: None)  # pyright: ignore[reportArgumentType]
    assert first == (len([s for s in steps if s.kind == "create"]), 0)
    second = CalendarGraph(graph.items)
    assert seed.apply(second, steps, context(), lambda _: None)[0] == 0  # pyright: ignore[reportArgumentType]


def test_the_sweep_names_only_case_items_and_removable_shares() -> None:
    graph = CalendarGraph(
        {
            "/me/calendars": [
                {"id": "c1", "name": "Calendar"},
                {"id": "c2", "name": "seed-v1 Shared calendar"},
            ],
            "/me/events": [
                {"id": "e1", "subject": "Daily standup"},
                {"id": "e2", "subject": "seed-v1 case-outlook_create_event-simple"},
            ],
            "/me/calendars/c2/events": [{"id": "e3", "subject": "seed-v1 case-x"}],
            "/me/contacts": [
                {"id": "k1", "displayName": "Lena Fischer"},
                {"id": "k2", "displayName": "seed-v1 case-outlook_create_contact-person"},
            ],
            "/me/calendars/c2/calendarPermissions": [
                {"id": "p1", "isRemovable": False},
                {"id": "p2", "isRemovable": True},
            ],
        }
    )
    assert list(family.sweep(graph, "mia")) == [  # pyright: ignore[reportArgumentType]
        ("DELETE", "/me/events/e2"),
        ("DELETE", "/me/calendars/c2/events/e3"),
        ("DELETE", "/me/contacts/k2"),
        ("DELETE", "/me/calendars/c2/calendarPermissions/p2"),
    ]


def test_cleanup_cases_deletes_what_the_sweep_names(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = CalendarGraph({"/me/events": [{"id": "e2", "subject": "seed-v1 case-x"}]})
    monkeypatch.setattr(seed, "FAMILIES", (family,))
    out: list[str] = []
    deleted = seed.cleanup_cases(graph, context(), 1, True, out.append)  # pyright: ignore[reportArgumentType]
    assert (deleted, out) == (1, ["would delete DELETE /me/events/e2"])
    assert graph.posts == []


def test_mia_tags_her_copy_of_the_invitation_and_nobody_else_tags_one() -> None:
    steps = plan(1)
    tag = next(step for step in steps if step.key == "event:a01")
    assert (tag.method, tag.path) == ("PATCH", "/me/events/{subject:Roadmap check}")
    assert tag.body == {
        "categories": ["seed-v1"],
        "singleValueExtendedProperties": [family._marks("event:a01")[0]],  # pyright: ignore[reportPrivateUsage]
    }
    lookup = steps[steps.index(tag) - 1]
    assert (lookup.lookup, dict(lookup.params)["$filter"]) == (
        "subject",
        "startswith(subject,'Roadmap check')",
    )
    assert [s for s in plan(2) + plan(3) if s.method == "PATCH"] == []


def test_the_tag_step_waits_for_the_invitation_and_runs_once() -> None:
    class Calendar(CalendarGraph):
        def get_all(self, path: str, params: Mapping[str, str]) -> Iterator[dict[str, Any]]:
            if "$filter" in params and params["$filter"].startswith("startswith"):
                yield {"id": "copy1", "subject": "Roadmap check"}
            else:
                yield from super().get_all(path, params)

    steps = [s for s in plan(1) if s.phase == "cal-invites"]
    graph = Calendar()
    assert seed.apply(graph, steps, context(), lambda _: None) == (1, 0)  # pyright: ignore[reportArgumentType]
    assert graph.posts == ["/me/events/copy1"]
    held = Calendar(
        {
            "/me/events": [
                {"id": "copy1", "singleValueExtendedProperties": [family._marks("event:a01")[0]]}
            ]
        }
    )  # pyright: ignore[reportPrivateUsage]
    assert seed.apply(held, steps, context(), lambda _: None) == (0, 1)  # pyright: ignore[reportArgumentType]
    with pytest.raises(seed.ConfigError, match="earlier phase"):
        _ = seed.apply(CalendarGraph(), steps, context(), lambda _: None)  # pyright: ignore[reportArgumentType]
